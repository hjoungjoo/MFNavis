# MFNavis m2.6.16 — Package the Nox worker termination test fix

Pin MFDS **v0.4.3**. Its parent-death regression treats `ProcessLookupError`
while opening or reading `/proc/<pid>/stat` as a confirmed worker exit,
preserving the two-second deadline and failure for a surviving worker.
The corrected test is now included in the installed package, addressing the
intermittent Nox 3.11 failure seen in m2.6.15 release CI.

Update development and process-only commercial locks with the actual source
commit and aarch64/x86_64 archive and manifest SHA256 values. Detection
algorithms, C ABI 1 and MFDS1 remain compatible. The m2.6.15 SkySafari,
LCD Stop tracking and overlay-title fixes are included.

Use Raspberry Pi OS **Trixie 64-bit / Python 3.13**, as the installation user:

```bash
wget -O /tmp/mfnavis-m2.6.16-setup.sh https://raw.githubusercontent.com/hjoungjoo/MFNavis/m2.6.16/mfnavis_setup.sh &&
MFNAVIS_INSTALL_BRANCH=m2.6.16 bash /tmp/mfnavis-m2.6.16-setup.sh
```

Reboot after installation. See the [Trixie installation guide](../docs/mf_dev/mf_trixie_install_en.md).
This release provides software source and installation materials.

[Full comparison](https://github.com/hjoungjoo/MFNavis/compare/m2.6.15...m2.6.16)
