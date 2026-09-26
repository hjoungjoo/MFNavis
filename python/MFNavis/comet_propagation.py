"""Batched Kepler propagation with the orbit axis preserved.

Adapted from Skyfield 1.55 skyfield/keplerlib.py, propagate(). The upstream
solver already advances multiple orbits, but its final reshape drops their
axis. Only the output shape differs here; Skyfield itself is not patched.
https://github.com/skyfielders/python-skyfield/blob/1.55/skyfield/keplerlib.py
"""

# Copyright © 2013–2018 Brandon Rhodes and available under the MIT license:
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import numpy as np
from numpy import (
    abs,
    amax,
    amin,
    array,
    atleast_1d,
    clip,
    copy,
    copyto,
    exp,
    full_like,
    log,
    newaxis,
    repeat,
    sqrt,
    sum,
    zeros_like,
)
from skyfield.functions import dots, length_of
from skyfield.keplerlib import dpmax, stumpff
from skyfield.sgp4lib import _cross


def propagate(position, velocity, t0, t1, gm):
    """Propagates a position and velocity vector with an array of times.

    Based on the function toolkit/src/spicelib/prop2b.f from the SPICE toolkit,
    which can be downloaded from naif.jpl.nasa.gov/naif/toolkit_FORTRAN.html

    Parameters
    ----------
    position : ndarray
       Position vector with shape (3,) or orbit batch with shape (3, N)
    velocity : ndarray
        Velocity vector with the same shape as position
    t0 : float
        Time corresponding to the initial state, scalar or one per orbit
    t1 : float or ndarray
        Time or times to propagate to
    gm : float
        Gravitational parameter in units that match the other arguments
    """
    output_shape = position.shape + np.shape(t1)

    gm = atleast_1d(gm)
    if (gm <= 0).any():
        raise ValueError("'gm' should be positive")
    if (length_of(velocity)).any() == 0:
        raise ValueError("Velocity vector has zero magnitude")
    if (length_of(position)).any() == 0:
        raise ValueError("Position vector has zero magnitude")

    if position.ndim == 1:
        position = position[:, newaxis]
    if velocity.ndim == 1:
        velocity = velocity[:, newaxis]

    r0 = length_of(position)
    rv = dots(position, velocity)

    hvec = _cross(position, velocity)
    h2 = dots(hvec, hvec)

    if (h2 == 0).any():
        raise ValueError("Motion is not conical")

    eqvec = _cross(velocity, hvec) / gm + -position / r0
    e = length_of(eqvec)
    q = h2 / (gm * (1 + e))

    f = 1 - e
    b = sqrt(q / gm)

    br0 = b * r0
    b2rv = b * b * rv
    bq = b * q
    qovr0 = q / r0

    maxc = amax(array([abs(br0), abs(b2rv), abs(bq), abs(qovr0 / bq)]), axis=0)

    hyperbolic = f < 0
    bound = zeros_like(f)

    fixed = log(dpmax / 2) - log(maxc[hyperbolic])
    rootf = sqrt(-f[hyperbolic])
    logf = log(-f[hyperbolic])
    bound[hyperbolic] = amin(
        array([fixed / rootf, (fixed + 1.5 * logf) / rootf]), axis=0
    )

    logbound = (log(1.5) + log(dpmax) - log(maxc[~hyperbolic])) / 3
    bound[~hyperbolic] = exp(logbound)

    # each of these arrays has 1 entry per orbit, so its shape is (#orbits, 1)
    f = f[:, newaxis]
    bq = bq[:, newaxis]
    b2rv = b2rv[:, newaxis]
    br0 = br0[:, newaxis]
    qovr0 = qovr0[:, newaxis]
    bound = bound[:, newaxis]

    def kepler(x):
        _, c1, c2, c3 = stumpff(f * x * x)
        return x * (br0 * c1 + x * (b2rv * c2 + x * bq * c3))

    def kepler_1d(x, orb_inds):
        _, c1, c2, c3 = stumpff(x * x * repeat(f, orb_inds))
        return x * (
            c1 * repeat(br0, orb_inds)
            + x * (c2 * repeat(b2rv, orb_inds) + x * (c3 * repeat(bq, orb_inds)))
        )

    t1 = atleast_1d(t1)
    t0 = atleast_1d(t0)
    if len(t0) == 1:
        t0 = repeat(t0, position.shape[1])

    # shape of 2 dimensional arrays from here on out should be (#orbits, len(t1))
    dt = t1 - t0[:, newaxis]

    x = dt / bq
    copyto(x, -bound, where=(x < -bound))
    copyto(x, bound, where=(x > bound))

    kfun = kepler(x)

    past = dt < 0
    future = dt > 0

    upper = zeros_like(dt, dtype="float64")
    lower = zeros_like(dt, dtype="float64")
    oldx = zeros_like(dt, dtype="float64")

    copyto(lower, x, where=past)
    copyto(upper, x, where=future)

    while (kfun[past] > dt[past]).any():
        copyto(upper, lower, where=past)
        lower[past] *= 2
        copyto(oldx, x, where=past)
        orb_ind = sum(past, axis=1)
        x[past] = clip(lower[past], repeat(-bound, orb_ind), repeat(bound, orb_ind))
        if (x[past] == oldx[past]).any():
            raise ValueError(
                "The input delta time (dt) has a value of {0}."
                "This is beyond the range of DT for which we "
                "can reliably propagate states. The limits for "
                "this GM and initial state are from {1}"
                "to {2}.".format(dt, kepler(-bound), kepler(bound))
            )
        kfun[past] = kepler_1d(x[past], orb_ind)

    while (kfun[future] < dt[future]).any():
        copyto(lower, upper, where=future)
        upper[future] *= 2
        copyto(oldx, x, where=future)
        orb_ind = sum(future, axis=1)
        x[future] = clip(upper[future], repeat(-bound, orb_ind), repeat(bound, orb_ind))
        if (x[future] == oldx[future]).any():
            raise ValueError(
                "The input delta time (dt) has a value of {0}."
                "This is beyond the range of DT for which we "
                "can reliably propagate states. The limits for "
                "this GM and initial state are from {1} "
                "to {2}.".format(dt, kepler(-bound), kepler(bound))
            )
        kfun[future] = kepler_1d(x[future], orb_ind)

    x = copy(upper)
    copyto(x, (upper + lower) / 2, where=(lower <= upper))

    lcount = zeros_like(dt)
    mostc = full_like(dt, 1000)
    not_done = (lower < x) & (x < upper)

    while not_done.any():
        orb_inds = sum(not_done, axis=1)
        kfun[not_done] = kepler_1d(x[not_done], orb_inds)

        high = (kfun > dt) & not_done
        low = (kfun < dt) & not_done
        same = (~high & ~low) & not_done

        copyto(upper, x, where=(high | same))
        copyto(lower, x, where=(low | same))

        condition = not_done & (mostc > 64) & (upper != 0) & (lower != 0)
        mostc[condition] = 64
        lcount[condition] = 0

        copyto(x, upper, where=(not_done & (lower > upper)))
        copyto(x, (upper + lower) / 2, where=(not_done & (lower <= upper)))

        lcount += 1
        not_done = (lower < x) & (x < upper) & (lcount < mostc)

    c0, c1, c2, c3 = stumpff(f * x * x)
    br = br0 * c0 + x * (b2rv * c1 + x * bq * c2)

    pc = 1 - qovr0 * x * x * c2
    vc = dt - bq * x**3 * c3
    pcdot = -qovr0 / br * x * c1
    vcdot = 1 - bq / br * x * x * c2

    position_prop = (
        pc[newaxis, :, :] * position[:, :, newaxis]
        + vc[newaxis, :, :] * velocity[:, :, newaxis]
    )
    velocity_prop = (
        pcdot[newaxis, :, :] * position[:, :, newaxis]
        + vcdot[newaxis, :, :] * velocity[:, :, newaxis]
    )

    position_prop.shape = output_shape
    velocity_prop.shape = output_shape
    return position_prop, velocity_prop
