# MFNavis

Repository: **https://github.com/hjoungjoo/MFNavis**. Installation uses `~/MFNavis` and `~/MFNavis_data`.

Product by **MagicFly**, sold and distributed by **FNPD 한국**.
Derived from PiFinder; historical upstream documentation is retained separately.
See [third-party notices](THIRD_PARTY_NOTICES.md) and [release policy](docs/MFNAVIS_RELEASE_ko.md).

[English](./README.md) | [한국어](./README_ko.md)

MFNavis is based on the original [PiFinder™](https://github.com/brickbots/PiFinder)
and supports Raspberry Pi OS Bookworm 64-bit on Pi 4, Pi 5, and CM5. It adds
practical features including web catalogs, optional INDI mount control, and
operational documentation. The original creator's project description and
basic references remain in [the upstream archive](README.upstream.md).

## Development quick start

Sales images must follow the [commercial release policy](docs/MFNAVIS_RELEASE_ko.md).
The default developer MFDS lock is not a commercial package.

### 1. Prepare Raspberry Pi OS

Install **Raspberry Pi OS Bookworm 64-bit** on the Pi 4, Pi 5, or CM5 boot
media with Raspberry Pi Imager. Configure a username, hostname, SSH, and Wi-Fi
before first boot, then log in as that user and confirm internet access.
Choose Bookworm explicitly for this installation.

See the [Raspberry Pi OS installation instructions](https://www.raspberrypi.com/documentation/computers/getting-started.html#install-an-operating-system)
for imaging and first boot, and the [board compatibility guide](./docs/mf_dev/mf_pifinder_rpi4_pi5_compatibility_ko.md)
for Pi 4/Pi 5/CM5 wiring differences.

### 2. Install MFNavis: release or main

Check the [MFNavis releases page](https://github.com/hjoungjoo/MFNavis/releases)
for the latest published version, its exact tag, and release-specific instructions.
Use the tagged release for a fixed version, or `main` for the latest development
changes. These instructions install MFNavis onto the prepared OS.

Run **one** of the following on a new installation, as the target OS user
without `sudo`; the script requests sudo where needed. It installs dependencies,
configures hardware interfaces and services, and **automatically installs the MFDS
detector**. The installation method differs by version:

| Version | Automatic detector installation |
| --- | --- |
| Published release | Uses the detector installation method included in the selected tag. Check the release notes for installation requirements and any build steps. |
| `main` | Downloads and verifies the MFDS binary release pinned in `deployment/mfds.lock.json`; no detector source build is required. |

Both paths are handled by the installation script; no separate manual MFDS
installation is needed.

**Published release:**

The command automatically looks up the latest published release on GitHub and
installs that tag. No version entry is needed. If the lookup fails, installation
stops. Use these commands for a new installation or an existing release update.

```bash
MFNAVIS_RELEASE_TAG="$(python3 -c 'import json, urllib.request; print(json.load(urllib.request.urlopen("https://api.github.com/repos/hjoungjoo/MFNavis/releases/latest"))["tag_name"])')" &&
[ -n "$MFNAVIS_RELEASE_TAG" ] &&
wget -O /tmp/mfnavis-setup.sh "https://raw.githubusercontent.com/hjoungjoo/MFNavis/${MFNAVIS_RELEASE_TAG}/mfnavis_setup.sh" &&
MFNAVIS_INSTALL_BRANCH="$MFNAVIS_RELEASE_TAG" bash /tmp/mfnavis-setup.sh
```

**Development version (main):**

```bash
wget -O /tmp/mfnavis-setup.sh https://raw.githubusercontent.com/hjoungjoo/MFNavis/main/mfnavis_setup.sh &&
MFNAVIS_INSTALL_BRANCH=main bash /tmp/mfnavis-setup.sh
```

After the script reports successful completion, reboot:

```bash
sudo reboot
```

#### Update an existing installation to the latest main or release

Connect over SSH as the installation's OS user, check the checkout, and back
up `~/MFNavis_data` and any local changes first. The setup script reapplies
dependencies and service configuration as well as updating the code.

**Update to the latest `main`:**

```bash
git -C ~/MFNavis status -sb
wget -O /tmp/mfnavis-setup.sh https://raw.githubusercontent.com/hjoungjoo/MFNavis/main/mfnavis_setup.sh &&
MFNAVIS_INSTALL_BRANCH=main bash /tmp/mfnavis-setup.sh &&
sudo reboot
```

**Update to the latest published release:** rerun the **Published release**
commands above, then `sudo reboot`. This selects the latest published GitHub
tag, not the `release` branch. Switching an existing installation to a tag
requires that release to contain the updated setup script with checkout
switching support.

An existing tagged release checkout can switch to `main` or a newer release
tag when the target is a fast-forward from the installed commit. Setup stops
if tracked files have local changes or the target would replace local history;
inspect the checkout with `git -C ~/MFNavis status -sb` in that case. If you
use a custom data directory, pass `MFNAVIS_DATA_DIR=/absolute/path` to the
update command as well.

#### Installation paths and existing checkouts

| Situation | Behavior / action |
| --- | --- |
| User `pifinder` | Code: `/home/pifinder/MFNavis`; data: `/home/pifinder/MFNavis_data`. |
| Another OS user | The same commands use that user's home: `~/MFNavis` and `~/MFNavis_data`. Use that user's account for subsequent commands. |
| Custom code directory, such as `~/MFNavis_main` | The setup script always targets `MFNavis` in the selected user's home, even when launched elsewhere; setting `MFNAVIS_REPO_DIR` does not override this. Use the standard location for a new installation. |
| Custom data directory | Pass `MFNAVIS_DATA_DIR=/absolute/path` with the installation command. Use the same value for later updates and cache commands. This does not move existing data. |
| `~/MFNavis` already exists | Setup fast-forwards to the branch or tag selected by `MFNAVIS_INSTALL_BRANCH`. Without it, setup updates the current branch; a tagged checkout requires an explicit target. |
| Existing tagged release checkout | Use the latest `main` command to switch to that branch or the published-release command to switch to a newer tag. |

`mfnavis_update.sh` updates **code only** on the current branch. It cannot
update a tagged checkout and refuses dependency, service-template, or OS
configuration changes. Use the full setup commands above to update `main` or
a release.

See the [MFDS binary installation guide](./docs/MFDS_BINARY_DISTRIBUTION_ko.md)
for package details. INDI mount support is optional: setup installs it only
when an INDI archive is available/configured; otherwise follow the
[INDI installation guide](./docs/mf_dev/mf_indi_mount_install_en.md).

### 3. Download offline caches

**The full image download takes a long time.** Thousands of survey images can
take hours depending on the connection and survey servers; reserve time before
an observing trip. Keep the MFNavis itself online and powered, and allow at
least **6 GB free** for the full POSS+SDSS cache. A phone connected to MFNavis's
AP alone does not necessarily give the device internet access.

From the installed repository, build the star/catalog runtime caches and
download both image surveys:

```bash
cd ~/MFNavis
python3 scripts/warm_pifinder_caches.py
```

To download only the POSS images used by the device and web catalog:

```bash
python3 scripts/warm_pifinder_caches.py --images poss
```

Use `--images none` to prepare runtime caches without downloading images.
The terminal shows progress; `Cache warm-up complete` indicates completion.
You can stop with `Ctrl-C` and rerun the same command to resume; existing images
are skipped. Keep the SSH session open while downloading. For a custom data
location, prefix the command with `MFNAVIS_DATA_DIR=/absolute/path`.

[Offline cache guide](./docs/mf_dev/mf_cache_download_en.md) |
[한국어](./docs/mf_dev/mf_cache_download_ko.md)

### 4. Basic device setup

1. **Check startup and controls.** After reboot, confirm the LCD and keypad
   respond. See [input controls](./docs/mf_dev/mf_input_controls_en.md) and
   [keyboard mapping](./docs/mf_dev/mf_keyboard_mapping_en.md).
2. **Select the hardware.** In `Settings > Advanced`, set `MFNavis Type` to
   match the mounting orientation, select `Camera Type`, and check the GPS
   type, port, and baud rate in `GPS Settings`. Follow any restart prompts.
3. **Check networking and the web UI.** On the same network, open
   `http://<hostname>.local` (`http://pifinder.local` if that is your hostname).
   In AP mode, use `http://10.10.10.1` if name resolution fails. See
   [AP+STA setup](./docs/mf_dev/mf_wifi_apsta_ko.md) to configure field Wi-Fi.
4. **Confirm location and time.** Outdoors, use `Start > GPS Status` and wait
   for a fix. Without GPS, enter location and time in `Tools > Place & Time`.
5. **Focus the lens.** Remove the lens cap, point at a clear star field, and
   open `Start > Focus`. Adjust the lens for sharp stars and a low HFD reading.
6. **Measure the lens automatically.** Select
   `Settings > Advanced > Lens > Auto (Measure)` and hold the device still.
   After five stable star frames, the screen shows `MEASURED`, the measured
   field of view, and focal length. The result is automatically saved as a
   **Manual** lens; seeing Manual selected afterwards is normal. Auto measures
   field of view and effective focal length; it does not focus the lens, so
   complete the previous step first. If stars are insufficient or measurement
   fails, check focus and sky conditions, then retry. Pressing LEFT during
   measurement cancels it and keeps the previous lens setting.
7. **Measure lens distortion.** After Auto completes, select
   `Settings > Advanced > Distortion > Measure Sky`. Aim at a star field with
   stars extending to the image edges and hold still until at least five valid
   frames and a stable result produce `MEASURED`. The result is saved
   automatically. Press LEFT to return, then check `Distortion > Status` for
   `Sky measured` and the `k1` value. If `Need edge stars` persists, point at a
   more evenly populated star field and hold still again. Auto and distortion
   measurement are separate operations. Repeat both after changing the lens
   or camera, then confirm that sky positions solve. See the
   [lens correction guide](./docs/mf_dev/mf_lens_distortion_correction_en.md)
   for profile application conditions and details.
8. **Align with the telescope.** Center a known star in the eyepiece and use
   `Start > Align` to align MFNavis's pointing with the telescope. Select a
   catalog target and check the Push-to directions.
9. **Configure optional mount control.** INDI is disabled by default. Follow
   the [INDI setup guide](./docs/mf_dev/mf_indi_mount_install_en.md) and verify
   connection, GoTo, and Sync with Telescope Simulator before a physical mount.

See the [quick-start manual](./docs/source/quick_start.rst) and
[user manual](./docs/source/user_guide.rst) for detailed device operation.

### 5. MF feature documentation

The [MF additional-features index](./docs/mf_dev/mf_additional_features_en.md)
covers web catalogs, location catalogs, LiveCam, automatic exposure, MFDS,
SQM, and IMU calibration. Its Korean equivalent is
[available here](./docs/mf_dev/mf_additional_features_ko.md). For validation
status, see the [feature review checklist](./docs/mf_dev/mf_feature_review_checklist_en.md).

---

## Upstream reference / 원본 프로젝트 자료

[Historical upstream documentation](README.upstream.md) is preserved for provenance.

[Product paths / 제품 경로 이전](docs/MFNAVIS_PATHS_ko.md)
