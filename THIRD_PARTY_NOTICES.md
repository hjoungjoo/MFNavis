# MFNavis — third-party notices

Product: **MFNavis** · Sales and distribution: **FNPD Korea** · Development and modifications: **MagicFly**

MFNavis is derived from PiFinder. PiFinder is the name of the original project;
it is not this product's name and does not imply official sales or endorsement
by the original project. Original copyright notices are retained, and MagicFly's
modifications are identified separately. GPL-covered components may be used,
modified and redistributed under the GPL; product sales terms do not restrict
these rights. The warranty disclaimers in the original licenses apply.

| Component | Source and copyright holders | Terms and included license text |
|---|---|---|
| PiFinder / MF_PiFinder and derived modifications | Original PiFinder authors and contributors; modifications by MagicFly | [GPLv3](LICENSES/GPL-3.0.txt); retain the original notices in each file |
| MFDS native | Code written or modified by MagicFly, plus other original notices | The FSL-to-MIT-after-five-years policy in the installed `python/MFDS/LICENSE` and `LICENSING.md` |
| MFDS PiFinder integration and preprocessing | PiFinder contributors and the authors of each file | GPLv3; FSL commercial restrictions do not apply |
| MFDS legacy MIT | PiFinder contributors identified in the original notice | [Original MIT license](LICENSES/MIT-MFDS-legacy.txt); previous permissions remain in effect |
| Tetra3 and included derived solver | Authors identified in `python/PiFinder/tetra3/VENDORED.md` and the original files | [Apache-2.0](LICENSES/Apache-2.0-Tetra3.txt); retain original attribution |
| SEP 1.4.1 | [SEP authors](LICENSES/SEP-AUTHORS.md) and the original authors of the included SExtractor code | LGPL-3.0-or-later: [LGPLv3](LICENSES/LGPL-3.0.txt) plus GPLv3; provide a distribution that permits modification and replacement, together with corresponding source |
| Python dependencies and bundled libraries | Original authors of each installed package | Original license text, NOTICE and METADATA collected from the product image in `OPEN_SOURCE_LICENSES/python/` |
| Debian/Raspberry Pi OS and native dependencies | Original authors of each installed package | Original copyright files and package lists in `OPEN_SOURCE_LICENSES/os/` |
| MFNavis Korean web font | Korean subset of the existing Sarasa bundle, renamed; Renzhi Li and original authors | [SIL Open Font License 1.1 and copyright notices](python/views/css/mfnavis-korean.LICENSE.txt); regenerate with `scripts/build_web_korean_font.py` |
| Web JS/CSS and fonts, astronomical catalogs, photographs, hardware designs | Original sources of the respective files | Check the original notices and terms separately from software licensing |

Naming a parent package does not replace the notices for bundled components,
such as the BLAS libraries in NumPy/SciPy. Use
`scripts/collect_product_licenses.py` to collect the original notices for the
dependencies actually installed in the build. Packages without license files
are recorded for review and must be resolved before shipment. This document is
not a completed legal audit approving the entire OS, data and fonts.

For corresponding-source media and installation of modified versions, see the
[sales and source-distribution guide](docs/MFNAVIS_RELEASE_en.md).
