# Open-source notices

StationPlay is built on the open-source work of others. This file lists the
parts in StationPlay's Docker image that come from others, and their
licenses. Each part keeps its own license.

## StationPlay

Copyright © 2026 egadgetboy. StationPlay is licensed under the GNU Affero
General Public License, version 3 (AGPL-3.0). See the [LICENSE](LICENSE)
file. Its source is at <https://github.com/egadgetboy/stationplay>.

Everything in the image that isn't listed below is StationPlay's own,
under the AGPL.

## Where to find the exact versions

The image records every Debian package installed in it, with its exact
version and the source package it's built from, in
`/opt/stationplay/third-party-packages.txt` (one line each, such as
`libavcodec61 <version> (source: ffmpeg <version>)`). Each Debian
package's own copyright and license notice is in the image at
`/usr/share/doc/<package>/copyright`.

To get the source of a Debian package at the exact version installed, use
the source package and version in that file:

- <https://sources.debian.org/src/ffmpeg/> (choose the version), or
- <https://snapshot.debian.org/package/ffmpeg/> (choose the version), or
- `apt-get source ffmpeg=<version>` on a Debian system with source
  packages turned on.

The same works for every package in the list: replace `ffmpeg` with its
source package.

## FFmpeg

- **What:** Debian's `ffmpeg` package (the `ffmpeg` and `ffprobe` programs)
  and the FFmpeg libraries it installs (`libavcodec`, `libavformat`,
  `libavfilter`, `libavutil`, `libswscale`, `libswresample` and others).
  StationPlay runs these programs to do all its video work. It doesn't
  change them.
- **License:** Most of FFmpeg's code is under the GNU Lesser General Public
  License, version 2.1 or later (LGPL-2.1-or-later). Debian builds FFmpeg
  with its GPL parts turned on, so FFmpeg as installed in the image is
  under the GNU General Public License, version 2 or later
  (GPL-2.0-or-later). Some files carry other licenses, all listed in
  `/usr/share/doc/ffmpeg/copyright`. In the running container,
  `ffmpeg -L` prints the license of the build.
- **Libraries FFmpeg uses:** Debian installs the libraries FFmpeg needs
  (for example x264, x265, libvpx, dav1d and opus). Each is under its own
  license, in its own `/usr/share/doc/<package>/copyright`, and listed in
  `third-party-packages.txt`.
- **Source:** Debian's `ffmpeg` source package, at the version listed in
  `third-party-packages.txt` (see above). StationPlay's releases are
  source only: no image is published. Your image gets Debian's packages,
  FFmpeg's among them, from Debian on the day it's built, and
  `third-party-packages.txt` in it lists them. Each release also comes with
  `stationplay-<version>-packages.txt`, the packages in the image
  StationPlay's tests ran in, each with a link to its source. FFmpeg's
  upstream project is at
  <https://ffmpeg.org>.

## Fonts

- **DejaVu fonts** (Debian's `fonts-dejavu-core`), used to draw the
  "We'll be right back" card and station number badges. Copyright © 2003
  Bitstream, Inc. (Bitstream Vera); DejaVu's changes are in the public
  domain. License: the Bitstream Vera Fonts license, in
  `/usr/share/doc/fonts-dejavu-core/copyright`.
- **Montserrat** (in `app/assets/fonts/`), used to draw the Intro Bumper,
  Station ID card and corner clock. Copyright 2024 The Montserrat.Git
  Project Authors (<https://github.com/JulietaUla/Montserrat>). License:
  SIL Open Font License, version 1.1, in `app/assets/fonts/OFL.txt`.

StationPlay's page uses no web fonts: it uses the fonts already on your
device.

## Video drivers

These are installed so StationPlay can use a GPU. They're optional: if one
can't be installed, the image still builds.

- **Mesa VA-API drivers** (Debian's `mesa-va-drivers`), for AMD GPUs.
  Mostly under the MIT license, with some parts under other licenses. See
  `/usr/share/doc/mesa-va-drivers/copyright`.
- **vainfo** (Debian's `vainfo`, from libva-utils), for troubleshooting.
  MIT license. See `/usr/share/doc/vainfo/copyright`.
- **Intel Media Driver** (Debian's `intel-media-va-driver-non-free`, on
  x86-64 only), for Intel GPUs. Its source is under the MIT and BSD-3-Clause
  licenses. Debian places it in its "non-free" section because it includes
  some parts that come without source code. See
  `/usr/share/doc/intel-media-va-driver-non-free/copyright` for its terms.
- **The libraries they need** (such as libva, libdrm and LLVM) are each
  under their own license, in their own `/usr/share/doc/<package>/copyright`.

## Debian and Python

- **Debian GNU/Linux 13 (trixie)**, the base of the image
  (`python:3.13-slim-trixie`). Each package is under its own license, in
  `/usr/share/doc/<package>/copyright`.
- **Python 3.13**, from the official Python image. License: Python
  Software Foundation License, version 2 (PSF-2.0). See
  `/usr/local/lib/python3.13/LICENSE.txt` in the image, or
  <https://docs.python.org/3/license.html>.
- **pip**, installed with Python. MIT license.

## Python packages

Installed from `requirements.txt` at these exact versions. Each package's
license file is in the image, in its `.dist-info` folder under
`/usr/local/lib/python3.13/site-packages/`.

| Package | Version | License |
|---|---|---|
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| certifi | 2026.7.22 | MPL-2.0 |
| click | 8.5.0 | BSD-3-Clause |
| fastapi | 0.141.1 | MIT |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| pydantic | 2.13.5 | MIT |
| pydantic-core | 2.46.5 | MIT |
| starlette | 1.7.0 | BSD-3-Clause |
| typing-extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | MIT |
| uvicorn | 0.46.0 | BSD-3-Clause |

certifi's MPL-2.0 covers its own files: its source is at
<https://github.com/certifi/python-certifi>, and the copy in the image is
unchanged.
