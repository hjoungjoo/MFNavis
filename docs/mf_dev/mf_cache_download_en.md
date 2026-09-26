# MFNavis Offline Cache Download Guide

[English](mf_cache_download_en.md) | [한국어](mf_cache_download_ko.md)

## Purpose and scope

`scripts/warm_mfnavis_caches.py` prepares rebuildable local caches while the
MFNavis has internet access. It makes catalog browsing and catalog-detail
pages faster and keeps cached object images available when the MFNavis is
offline.

The command creates or downloads only the following data:

| Location | Content | Purpose |
| --- | --- | --- |
| `~/MFNavis_data/cache/hip_main.pkl` | Parsed Hipparcos star catalog | Faster star-field startup |
| `~/MFNavis_data/cache/hip_bv.npz` | Hipparcos B-V color-index lookup | Faster SQM color-correction startup |
| `~/MFNavis_data/cache/catalogs/` | Composite-object catalog cache | Faster catalog search and list startup |
| `~/MFNavis_data/catalog_images/` | POSS/SDSS survey images | Object pictures in MFNavis and the web catalog |

It does not change observing records, equipment settings, Wi-Fi credentials,
user photos, or logs. It also does not pre-create condition-specific data such
as a camera warm-pixel map.

## Before you start

- The **MFNavis itself** must have internet access. A phone connected to
  MFNavisAP does not necessarily provide internet access to the MFNavis.
- Leave enough power and storage available. The prebuilt image's 13,000+
  catalog images occupy about 5 GB; allow **at least 6 GB free** for the full
  POSS+SDSS download. The final size varies with the current catalog and
  survey responses.
- Do not run this during an observing session. Cache generation uses CPU,
  network bandwidth, and SD-card I/O.

## Default command

From the repository root, run:

```bash
cd ~/MFNavis
python3 scripts/warm_mfnavis_caches.py
```

On Trixie, the script automatically uses the installed `.venv-trixie` Python.
An already active virtual environment is used instead. To select an interpreter
explicitly, set `MFNAVIS_PYTHON=/path/to/venv/bin/python`; this takes precedence
over both automatic choices. The image downloader uses the same interpreter.

The default sequence is:

1. Build the Hipparcos star-field and B-V color-index caches.
2. Build the complete composite-object catalog cache.
3. Download POSS and SDSS survey images through `MFNavis.gen_images`.

Ten images are downloaded concurrently by default. Use a lower worker count
on an unreliable or shared network:

```bash
python3 scripts/warm_mfnavis_caches.py --workers 4
```

## Choose the cache scope

MFNavis and the web catalog use POSS images. To avoid storing SDSS images,
download only POSS:

```bash
python3 scripts/warm_mfnavis_caches.py --images poss
```

To build only the fast-start local caches, without images:

```bash
python3 scripts/warm_mfnavis_caches.py --images none
```

To download images without rebuilding the runtime caches:

```bash
python3 scripts/warm_mfnavis_caches.py --skip-runtime
```

## Check progress and completion

The command prints each runtime-cache step and the image-download progress.
In another terminal, inspect the stored size and file counts with:

```bash
du -sh ~/MFNavis_data/cache ~/MFNavis_data/catalog_images
find ~/MFNavis_data/catalog_images -name '*_POSS.jpg' | wc -l
find ~/MFNavis_data/catalog_images -name '*_SDSS.jpg' | wc -l
```

`Cache warm-up complete` indicates success. Afterwards, disconnect internet
access and open a catalog detail page to verify that a cached object image is
still shown.

## Stop and resume

Press `Ctrl-C` to stop. When internet access is available again, run the same
command to continue: `gen_images` skips image files that already exist, and
valid runtime caches are reused.

Static cache generation does not start planet/comet timers or download comet
data. A JPEG is moved to its final path only after the download is complete.
Transient download failures produce a nonzero exit status; rerun the same command
to retry. Objects outside SDSS coverage count as `unavailable`, not failed.
The SDSS cutout API's `404` response with `image/jpeg` content means the
coordinate is outside the survey footprint. Those responses and blank cutouts
are recorded beside the JPEG path in `.unavailable.json` files, so subsequent
runs avoid requesting the same unavailable cutout again. The record is reused
only for the same coordinate, survey URL, and cutout settings; the image
generator's `--force` option bypasses it. HTML `404` responses, server errors,
and timeouts remain failures that can be retried.
If an older version left a corrupt image, remove only that object's JPEG and
rerun the command. Settings and observing records are unaffected.

## Troubleshooting

| Symptom | Check and action |
| --- | --- |
| No image files are added | Confirm internet, DNS, and HTTPS access on the MFNavis itself. |
| Storage becomes full | Use `--images poss` or use larger storage. |
| Download is too slow | Adjust `--workers` between 4 and 10; lower values can be more reliable on weak networks. |
| A web catalog detail page still has no image | That object may not have a POSS survey image. The web server always prefers an existing local cache file. |

## Implementation references

- Runner: `scripts/warm_mfnavis_caches.py`
- Image generator: `python/MFNavis/gen_images.py`
- Web catalog image route: `python/MFNavis/web_catalogs.py`
- Cache path definitions: `python/MFNavis/utils.py`
