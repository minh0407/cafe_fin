# Document renderer assets and notices

Noto Sans Regular and Bold are unmodified fonts from
https://github.com/notofonts/noto-fonts/tree/ffebf8c1ee449e544955a7e813c54f9b73848eac/hinted/ttf/NotoSans
(downloaded 2026-11-06). Their license and copyright are in `OFL-NotoSans.txt`.
Redistribute that license with both fonts. The fonts are not sold separately.

| File | SHA-256 |
| --- | --- |
| NotoSans-Regular.ttf | b85c38ecea8a7cfb39c24e395a4007474fa5a4fc864f6ee33309eb4948d232d5 |
| NotoSans-Bold.ttf | c976e4b1b99edc88775377fcc21692ca4bfa46b6d6ca6522bfda505b28ff9d6a |

PDF uses these embedded TrueType fonts. DOCX references the Noto Sans family;
it does not embed fonts, and a document viewer can substitute its own font.

The `notices` directory contains unmodified license files from the exact
installed Windows distributions used by the foundation lockfile:

| Package | Version | Main license | Notice |
| --- | --- | --- | --- |
| reportlab | 4.4.9 | BSD | notices/reportlab-LICENSE |
| python-docx | 1.2.0 | MIT | notices/python-docx-LICENSE |
| pillow | 13.0.0 | MIT-CMU | notices/pillow-LICENSE |
| lxml | 6.1.1 | BSD-3-Clause | notices/lxml-LICENSE.txt, notices/lxml-LICENSES.txt |

These are not a substitute for the complete installer dependency notice
inventory. The Windows native wheels must also be audited for their actual
bundled libraries (including libxml2/libxslt and Pillow codecs) when the
sidecar is built. Ship their notices with the installer. The development-only
PDF verifier pypdf 6.10.0 is BSD-3-Clause and is not required by the renderer.

The renderer uses the open-source ReportLab toolkit only. It does not import
commercial `rlextra`, `pyRXP`, Office automation, Pango or WeasyPrint. Do not
collect unrelated ReportLab DarkGarden GPL font assets; only the Noto font
files above are used by this renderer. The `python-docx/templates` directory
is required in the frozen sidecar.

Primary references: https://docs.reportlab.com/developerfaqs/ ;
https://github.com/python-openxml/python-docx/blob/master/pyproject.toml ;
https://github.com/lxml/lxml/blob/master/LICENSES.txt ;
https://github.com/python-pillow/Pillow/blob/main/LICENSE ;
https://pyinstaller.org/en/latest/hooks.html .
