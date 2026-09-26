use generate_script.py to generate a random testing script.

## Pre-populating MFNavis caches

Use `warm_mfnavis_caches.py` before an offline session to build the local
catalog/star-data caches and download the catalog survey images:

```bash
python3 scripts/warm_mfnavis_caches.py
```

The default downloads both POSS and SDSS images. The catalog and web detail
views use POSS; use this smaller option when that is all that is required:

```bash
python3 scripts/warm_mfnavis_caches.py --images poss
```

The command is safe to stop and re-run: image files already present in
`~/MFNavis_data/catalog_images` are skipped. Use `--images none` to warm only
the local runtime caches, or `--skip-runtime` to download only images.

The frequencies you can find in the script can be changed for certain cases
but are a good starting point.

Scripts can be generated like this:

```bash
python3.9 generate_script new_random_1k 1000
```

Scripts can be run locally like this:

```bash
python3.9 -m PiFinder.main -fh --camera debug --keyboard local -x --script new_random_1k   # 1k is the number of frames
```
