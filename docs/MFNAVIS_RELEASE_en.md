# MFNavis sales and source-distribution policy — 2026-09-23

## Product identity

The product name is **MFNavis**, the seller and distributor is **FNPD Korea**
(FNPD, based in the Republic of Korea), and the developer and modifier is
**MagicFly**. Do not use PiFinder as the product name in the UI, packaging or
product pages. Retain the original project name in attribution and licensing
information. Internal Python packages, service names, paths and repository
addresses are retained for compatibility. Do not claim trademark registration
or that this is an official product of the original PiFinder project.

Standard text for packaging and product pages:

> MFNavis — astronomical object finding and plate-solving system
> Sales and distribution: FNPD Korea | Development and modifications: MagicFly
> See the included materials for open-source components, licenses and instructions for installing modified versions.

## Providing GPL corresponding source

For physical product sales, use **GPLv3 section 6(a)**: include a durable medium
commonly used for software interchange, such as a separate USB storage device,
with the product. A GitHub link alone does not replace this medium. Include the
PiFinder-derived source matching the image exactly, the actual transformed
source of the MFDS GPL integration, build and installation scripts, required
interface definitions, corresponding source and modifications for the exact
versions of GPL/LGPL dependencies, licenses, NOTICE files and installation
information for modified versions. Assess applicable System Library exceptions
component by component; do not exclude everything merely because it is an OS
package.

For downloadable images, follow **section 6(d)** by providing equivalent access
to corresponding source at the same location at no additional charge. A separate
written offer under section 6(b) is not the default approach. The scope of rights
for MFDS native and review of combined distribution are separate matters; use of
IPC alone does not automatically determine the scope of GPL coverage.
Reference: https://www.gnu.org/licenses/gpl (section 6 and User Product
Installation Information).

## Installing modified versions

1. Back up the product's user-owned SD card. Use the included manifest and
   dependency lists to identify the OS, architecture, Python version and package
   versions matching the product image.
2. Copy the PiFinder source from the source medium to `~/PiFinder`. Preserve
   settings and observations in `~/PiFinder_data` separately. If the source path
   changes, update the systemd service's WorkingDirectory and ExecStart too.
3. Reproduce the environment using the included build and installation scripts
   and pinned dependencies. Use the included versions and offline archives so
   installation scripts do not fetch the latest branch instead.
4. Modify the desired GPL source and run it in the Python environment, or point
   the ExecStart of `pifinder.service` to the modified source. Provide the owner
   account's service-management permissions and the actual unit file.
5. Users must be able to replace or rebuild GPL/LGPL libraries with ABI-compatible
   modified versions. If installation is restricted by vendor-only signatures or
   private keys, provide the necessary installation information and permissions.
   Do not assume that keys absent from the current product exist.

Verify this procedure against the shipping image by restoring a blank SD card
and running a modified version. Attach the actual account name, service files,
commands and results to the shipment record. This document does not claim to be
a shipping manual whose physical-device restoration testing is complete.

## Image-specific pinning and shipment checks

`deployment/mfds.lock.json` pins the general MFDS 0.4.1 distribution. Its binary
is a development package that includes ctypes support; it is not itself a
commercial product image. A new package built with `make commercial` has different
hashes. The commercial lock must require `profile: commercial-process-only` and
reject general packages.

Record the following measured values for each image. Do not present example
versions as actual releases.

- Product firmware version, image filename and SHA256.
- MF_PiFinder tag, full commit and whether the source tree is clean.
- MFDS version, full commit, commercial profile and architecture.
- SHA256 of the MFDS archive and PACKAGE.json, and hashes of the contained files.
- Filename and SHA256 of the included corresponding source, plus hashes of the
  installation information and notice bundle.
- Actual Python/OS package versions and records resolving missing notices.

Before shipment, inspect `THIRD_PARTY_NOTICES.md`, `LICENSES/`, the collected
`OPEN_SOURCE_LICENSES/`, source media and installation manual together. Also
check web assets, fonts, catalogs, OS firmware, hardware/case designs and original
logos remaining on packaging. Historical images or CAD files containing PiFinder
branding are not automatically changed by renaming the current software.

Run the commercial installation checks as follows. These commands activate a
package, so use them only in a build or shipment-preparation environment.
Existing general locks and uncommitted candidates are rejected.

```sh
python3 scripts/install_mfds.py --commercial --lock deployment/mfds-commercial.lock.json --archive /path/to/MFDS-<version>-linux-<arch>-commercial.tar.gz
python/.venv/bin/python scripts/collect_product_licenses.py --output OPEN_SOURCE_LICENSES
```

`deployment/mfds-commercial.lock.json` pins the official MFDS v0.4.1 commercial
packages and actual hashes for both architectures. It adds
`"profile": "commercial-process-only"` to the existing lock's schema, version,
source_commit and assets structure; the URLs and both SHA256 values refer to
actual files. Future updates must not invent release URLs or hashes in advance.
Exit code 1 from the notice collector means missing original notices still need
review.

For the service in a commercial image, install
`deployment/mfnavis/20-commercial.conf` as
`mfnavis.service.d/20-commercial.conf`. The package itself excludes the loader,
so changing environment variables alone cannot restore ctypes access. Disable
bytecode generation so the installed commercial cache's file list remains
consistent with the manifest.

After completing the image and corresponding-source bundle, use the following
tool to record actual file hashes. It fails unless the PiFinder tree is clean,
the tag matches HEAD and the commercial MFDS package is clean. It does not
overwrite existing records. Separately verify source-bundle completeness and
installability through the shipment checks above.

```sh
python3 scripts/record_product_release.py --firmware-version <product-version> \
  --pifinder-tag <actual-tag> --image /path/to/MFNavis.img \
  --source-archive /path/to/corresponding-source.tar.gz \
  --mfds-archive /path/to/MFDS-<version>-linux-<arch>-commercial.tar.gz \
  --output /path/to/PRODUCT_RELEASE.json
```

Commercial images also include the `/etc/mfnavis-commercial` marker. When it is
present, normal setup/update operations accept only commercial locks and
packages, even if `--commercial` is omitted. Subsequent updates therefore cannot
silently revert to a general package containing ctypes. This work did not
install that marker or service configuration on the operating device.

For implementation, verification and outstanding shipment items, see the
[work report (Korean)](mf_report/mfnavis_commercial_20260923_ko.md).

## Product logo

The original is `images/MFNavis logo.png` (1254×1254 PNG). Do not modify it.
`PiFinder.branding.welcome_image()` preserves its aspect ratio and fits it below
the status bar in the boot splash service and the main service's startup console.
The shared web header, login page, favicon and home-screen app icon use the same
original through the relative symlink `python/views/images/mfnavis-logo.png`.
Include both the original PNG and the symlink in distributions. Python code
already loaded by a running service takes effect at the next service start;
boot-screen changes appear on the next boot.
