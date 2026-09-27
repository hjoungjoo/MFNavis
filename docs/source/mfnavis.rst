MFNavis product guide / 제품 안내
================================================================================

Identity
--------

* Product: **MFNavis**
* Creator/modifier: **MagicFly**
* Seller/distributor: **FNPD 한국**, Republic of Korea

The MFNavis logo appears during device boot and service startup, and in the
web interface and home-screen app icon. Device help pages describe MFNavis.
Original project logos and manuals are kept only as historical references.

Installation on Trixie
----------------------

The MFNavis installation baseline is **Raspberry Pi OS Trixie 64-bit** on
Raspberry Pi 4, Pi 5, and CM5, using **Python 3.13**. Prepare the OS with
Raspberry Pi Imager and configure your own username, hostname, SSH, and Wi-Fi.

Install the Trixie-based ``main`` branch as the target OS user:

.. code-block:: bash

   wget -O /tmp/mfnavis-setup.sh https://raw.githubusercontent.com/hjoungjoo/MFNavis/main/mfnavis_setup.sh &&
   MFNAVIS_INSTALL_BRANCH=main bash /tmp/mfnavis-setup.sh

Published releases retain their own OS requirements.
Source updates do not upgrade Bookworm to Trixie; back up user data before
preparing the new OS.

Setup creates ``~/MFNavis/.venv-trixie`` with access to OS Picamera2/GPIO
packages, installs the pinned MFDS binary, and verifies the Trixie/Python 3.13
INDI archive. INDI archive installation is required by default; app mount
control stays disabled until selected. MFNavis, splash, and INDI Web Manager
use the same runtime Python. Development uses ``.venv-dev-trixie``.

See the repository's
`English installation guide <https://github.com/hjoungjoo/MFNavis/blob/main/docs/mf_dev/mf_trixie_install_en.md>`_
and
`Korean installation guide <https://github.com/hjoungjoo/MFNavis/blob/main/docs/mf_dev/mf_trixie_install_ko.md>`_
for archive selection, custom paths, startup checks, and development commands.

The 2026-09-27 GoTo field test was reported by the user to have no major
problems on the tested Trixie setup. Earlier Pi 4/CM5 Bookworm checks are
historical results; separate Trixie hardware validation is still required.

Connect
-------

In access-point mode, connect to **MFNavisAP** and open ``http://10.10.10.1``.
In client mode, use the device's current hostname or assigned IP address.
The existing hostname need not contain the product name. Renaming the AP
requires phones/tablets previously using PiFinderAP to select the new network.
Saved client-network credentials and UUIDs are preserved.

Services
--------

The primary service is ``mfnavis.service``. The startup splash and AP helpers
use ``mfnavis_splash.service``, ``mfnavis_apsta_prepare.service`` and
``mfnavis_apsta_monitor.service``. Legacy service aliases remain available to
existing installation/update scripts. The login account is preserved. New code lives in ``~/MFNavis``, user data
in ``~/MFNavis_data``, and volatile state in ``/dev/shm/mfnavis``.
Services launch ``MFNavis.main``. Legacy path and Python import aliases remain
available for integrations and older tools.

Backup and diagnostics
----------------------

The web backup downloads as ``MFNavis_backup.zip``. Restore accepts existing
backup uploads regardless of their original filename. Legacy archive paths
are mapped into the selected MFNavis data directory. New application logs use ``mfnavis.log``. Legacy logs can still be
read and exported. Observation-list exports identify MFNavis as the producer;
existing observation-list file formats remain supported.

INDI status and errors use MFNavis in human-readable messages. Internal
configuration/IPC identifiers remain stable for saved settings and integrations.

Licenses and source
-------------------

Use the web footer's local third-party license notices and source/installation
information. Repository documents ``THIRD_PARTY_NOTICES.md`` and
``docs/MFNAVIS_RELEASE_ko.md`` describe the distribution scopes, source delivery
and installation information. PiFinder attribution is retained where it refers
to the original work. MFDS native, GPL integration and legacy MIT notices have
separate scopes.

Commercial images must use the separate process-only MFDS package and a pinned
commercial lock. Product branding does not turn the existing developer MFDS
package into a commercial release. See the release policy before shipping.
