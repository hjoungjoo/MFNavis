# Solver core provenance

Vendored from https://github.com/smroid/cedar-solve at 38c3f48f57d1005e9b65cbb26136f9f13ec0a1b0.
Apache-2.0 license and original Tetra notice retained in LICENSE.txt.
Only the solver core and its existing default database are included.
Cedar Detect binaries, client, protobuf definition and generated modules are excluded.
No solver algorithm changes were made during vendoring.

## Subsequent modifications

On 2026-09-15, MF_PiFinder commit `24bf58cd` modified `tetra3/tetra3.py`
to batch pattern hashes and accelerate collision probing, retaining a switch
for the previous search. That file carries an explicit modification notice.
The other eight retained upstream files, including the database and license,
matched the pinned upstream commit during the 2026-09-15 license audit.
Original Apache-2.0 and Tetra attribution notices remain in place.
