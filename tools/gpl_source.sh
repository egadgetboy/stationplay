# The source of FFmpeg, x264 and x265, at the exact versions in StationPlay's
# image: Debian's source packages (each one's .dsc and tarballs), downloaded
# into /out. The image includes them under the GPL, which asks that their
# source go with them, so each release carries this
# (stationplay-<version>-gpl-source.tar, made by release.yml).
#
# It runs inside the image, as root, with a folder mounted at /out:
#
#     docker run --rm -i --user 0 -v "$PWD/gpl:/out" ghcr.io/<you>/stationplay:<version> sh -s < tools/gpl_source.sh
#
# A version Debian no longer serves (one replaced since the image was built)
# stops it, saying which: nothing is published without its source.
set -eu
sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/debian.sources
apt-get update -qq
cd /out
for source in ffmpeg x264 x265; do
    version=$(dpkg-query -W -f '${source:Package} ${source:Version}\n' \
        | awk -v s="$source" '$1 == s { print $2; exit }')
    if [ -z "$version" ]; then
        echo "The image has nothing built from $source" >&2
        exit 1
    fi
    if ! apt-get source --download-only -qq "$source=$version" > /dev/null; then
        echo "Debian doesn't serve $source $version's source now: build the image again" >&2
        exit 1
    fi
    echo "$source $version"
done
