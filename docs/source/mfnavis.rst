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
existing installation/update scripts. The Python package and existing user
account/data paths remain compatible with the original installation.

Backup and diagnostics
----------------------

The web backup downloads as ``MFNavis_backup.zip``. Restore accepts existing
backup uploads regardless of their original filename; user data paths remain
unchanged. New application logs use ``mfnavis.log``. Legacy logs can still be
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
