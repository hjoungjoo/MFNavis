# Store the alignment point with its telescope

MFNavis adopts the per-telescope target pixel introduced in PiFinder 2.6.4.
Daytime alignment and successful LCD star alignment save the pixel on the
active telescope. Selecting a telescope on the LCD or web restores its point.
An unaligned telescope uses the existing global target pixel. If neither
value is usable, the resolver returns the native image centre.

Web edits preserve the point when the user renames a telescope. Deleting
another telescope preserves the active instrument. Saving an alignment uses
the same locked settings transaction and A0 FRAM backup as other equipment
changes. SkySafari sync and the LCD reticle reset apply to the current
session. Restarting restores the saved point for the selected telescope.

[Original PiFinder change](https://github.com/brickbots/PiFinder/pull/703)
