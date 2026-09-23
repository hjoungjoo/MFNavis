"""Compatibility import for the pinned MFDS cloud-background detector.

MFDS 0.3.2 imports this focal-length helper from its former module. Tile
overlays, exclusions and tile solving have been removed; optics owns the helper.
"""

from PiFinder.optics import active_focal_length_mm as active_focal_length_mm
