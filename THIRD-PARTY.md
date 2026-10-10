# Third-party licences

nexpaper itself is licensed under the **GNU Affero General Public License v3.0** (see [LICENSE](LICENSE)). This file
lists what it ships or depends on.

## Bundled with the app

These files travel inside the container image, so their notices travel with them.

| What | Copyright | Licence | Notice in the app |
|---|---|---|---|
| Fonts Fraunces and Figtree (via Fontsource) | The Fraunces and Figtree Project Authors | OFL-1.1 | `/licenses/fonts.txt` |
| Lucide icons (partly from Feather) | Lucide Contributors; Cole Bemis | ISC, MIT | `/licenses/lucide.txt` |
| OpenCV.js (the camera's edge finder, from the npm package `@techstark/opencv-js`, copied at build time) | OpenCV team and contributors | Apache-2.0 | `/scanner/opencv.LICENSE.txt` |
| jscanify (finds the sheet of paper with OpenCV; `frontend/public/scanner/jscanify.js`, unchanged) | ColonelParrot and contributors | MIT | `/licenses/jscanify.txt` |
| pdf.js (the pages of a document; the npm package `pdfjs-dist`, its character maps, standard fonts and decoders copied at build time) | Mozilla Foundation and contributors | Apache-2.0 | `/pdfjs/LICENSE` |

nexpaper loads no font, icon or script from another host.

## Backend

What `backend/requirements.txt` names, and what those packages bring along (checked against the installed set, which is
what the container image installs; on Linux `uvicorn[standard]` adds uvloop). The packages of the text recognition are listed below the table.

| Package | Licence |
|---|---|
| FastAPI, Starlette (the web framework), SQLAlchemy, pydantic, pydantic-core, pydantic-settings, annotated-types, annotated-doc, typing-inspection | MIT, Starlette BSD-3-Clause |
| anyio, h11, httptools, watchfiles, PyYAML, PyJWT, http-ece | MIT |
| argon2-cffi, argon2-cffi-bindings, cffi | MIT (cffi: MIT-0 for its own part) |
| uvicorn, httpx, httpcore, click, idna, segno, python-dotenv, websockets, pycparser | BSD-3-Clause |
| uvloop (Linux only) | MIT **or** Apache-2.0 |
| Pillow | MIT-CMU |
| cryptography | Apache-2.0 **or** BSD-3-Clause |
| tzdata (the IANA time zone database for Python) | Apache-2.0; the data itself is in the public domain |
| typing-extensions | PSF-2.0 |
| SQLite (the library inside Python) | Public domain |
| certifi (the CA bundle) | MPL-2.0; the file is unchanged and its source is public |
| pillow-heif | BSD-3-Clause for its own code; the binary wheels are **GPLv2** as a whole, see below |
| webauthn (py_webauthn, passkeys) | BSD-3-Clause |
| python-multipart (the body of an upload) | Apache-2.0 |
| pypdfium2 (draws the pages of a PDF) | BSD-3-Clause or Apache-2.0 for its own code; the PDFium library it carries is BSD-3-Clause, with parts under Apache-2.0, MIT and others, listed in the licence file of the package |
| img2pdf (a picture becomes a PDF without being re-encoded) | **LGPL-3.0**; nexpaper uses it as a library, unchanged, and the package can be replaced by another version |
| pikepdf (img2pdf uses it) | MPL-2.0; it carries QPDF (Apache-2.0) |
| lxml (pikepdf uses it) | BSD-3-Clause; it carries libxml2 and libxslt (MIT) |
| packaging | Apache-2.0 or BSD-2-Clause |
| cbor2 | MIT |
| pyOpenSSL | Apache-2.0 |
| pyasn1, pyasn1-modules | BSD-2-Clause, BSD-3-Clause |
| OCRmyPDF (drives Tesseract, writes the searchable copy) | MPL-2.0; used as a library, unchanged |
| fpdf2 (OCRmyPDF writes the text layer with it) | **LGPL-3.0**; used as a library, unchanged, replaceable |
| uharfbuzz (fpdf2 shapes text with it) | Apache-2.0; it carries HarfBuzz (MIT) |
| fontTools, pdfminer.six, pluggy, rich, markdown-it-py, mdurl, attrs, jsonschema, jsonschema-specifications, referencing, rpds-py, charset-normalizer | MIT |
| Pygments | BSD-2-Clause |
| defusedxml | PSF-2.0 |

### Text recognition: Tesseract

The image installs Tesseract from Debian (`tesseract-ocr`, Apache-2.0) with the trained data for German, English,
French, Dutch, Polish, Turkish and for finding the orientation of a page (`tesseract-ocr-*`, Apache-2.0), and Leptonica,
which Tesseract uses (BSD-2-Clause style). Their notices are in `/usr/share/doc/` of the image. Ghostscript is not in the
image: OCRmyPDF draws the pages with PDFium and writes a plain PDF, which needs none.

### HEIC photos: pillow-heif and the libraries it brings

To read iPhone photos (HEIC), as a profile picture or, later, as a document, nexpaper uses pillow-heif. Its binary wheels, and so the container
image, contain:

| Library | Licence |
|---|---|
| libheif | LGPL-3.0 |
| libde265 | LGPL-3.0 |
| x265 | GPL-2.0-or-later |

The wheel ships these notices in `pillow_heif-*.dist-info/licenses/`. GPL-2.0-or-later and LGPL-3.0 may be combined
with an AGPL-3.0 work, and the source of every part is public.

### WebP and AVIF pictures: Pillow and the libraries it brings

To take WebP and AVIF pictures as documents (what Android phones, newer cameras and browsers save), nexpaper uses Pillow, whose binary
wheels carry the decoders. Their notices are in `pillow-*.dist-info/licenses/LICENSE` of the wheel:

| Library | Licence |
|---|---|
| libwebp | BSD-3-Clause |
| libavif (with the AV1 decoder dav1d and, in the wheels that carry it, aom) | BSD-2-Clause |

A WebP or AVIF file is only ever decoded in the worker process, as the first frame, and turned into a PDF; the original is kept as it came.

## Frontend

| Package | Licence |
|---|---|
| React, React DOM, React Router, i18next, react-i18next, scheduler, cookie, set-cookie-parser, html-parse-stringify, void-elements, use-sync-external-store, @babel/runtime | MIT |
| lucide-react | ISC |
| pdfjs-dist | Apache-2.0 |
| Fontsource packages | MIT (the fonts themselves OFL-1.1, see above) |

Build and test tools (Vite, TypeScript, Tailwind CSS, Vitest, ruff, pytest) are not part of the image. Their code is not
in the finished interface either, except what Vite and Tailwind CSS (both MIT) compile into the files.

## The base image

The container starts from `python:3.13-slim` (Debian GNU/Linux; the Python Software Foundation licence for Python, and the
licences of the Debian packages, listed in `/usr/share/doc/` of the image). On top of it: `curl` (the curl licence, an MIT
style licence; for the health check), `gosu` (Apache-2.0; drops the rights at the start), and Tesseract with its trained
data (above). Nothing is downloaded when the container runs.

## Compatibility

All of the above may be combined into an AGPL-3.0 work. The obligation runs one way: nexpaper as a whole is
AGPL-3.0, and anyone who runs a modified version as a network service must offer its source.
