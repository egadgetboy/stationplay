# The base image, pinned: the same Python and Debian every time it's built,
# until this line changes. To update it, put the digest of
# python:3.13-slim-trixie today in its place: the "Digest:" that
# "docker buildx imagetools inspect python:3.13-slim-trixie" prints (the
# list of every platform's image, so it builds on ARM too), or the one in
# docker-library/repo-info's repos/python/remote/3.13-slim-trixie.md. The
# image workflow's tests then run on it before anything's published.
FROM python:3.13-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS stationplay

# ffmpeg does all the video work; the font is for the "We'll be right back"
# card and station number badges.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# GPU drivers: intel-media for Intel (Broadwell and newer, including 12th-gen
# UHD 770) and mesa for AMD. NVIDIA's libraries come from the NVIDIA
# container runtime instead. These are optional: if they can't be installed
# the image still builds and StationPlay encodes on the CPU. vainfo is for
# troubleshooting (docker exec stationplay vainfo).
RUN sed -i 's/^Components: main$/Components: main non-free/' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && (apt-get install -y --no-install-recommends mesa-va-drivers vainfo \
        || echo "WARNING: AMD VA-API driver not installed") \
    && if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
         apt-get install -y --no-install-recommends intel-media-va-driver-non-free \
         || echo "WARNING: Intel VA-API driver not installed"; \
       fi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/stationplay
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# COPY keeps whatever permissions the files had on the NAS, which may not
# let the user in the YAML read them. Make the app readable (and
# precompiled) for any user, whatever the source folder's permissions.
RUN python -m compileall -q app \
    && chmod -R a+rX /opt/stationplay

ENV DATA_DIR=/data \
    PORT=3310 \
    PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/tmp/cache \
    NVIDIA_DRIVER_CAPABILITIES=compute,video,utility

EXPOSE 3310
VOLUME /data

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"3310\")}/discover.json', timeout=4)" || exit 1

CMD ["python", "-m", "app.main"]

# The tests, in the image as it ships (the image workflow runs them here,
# and publishes the image only once they pass): pytest and the tests on top,
# run as the user the YAML files give, and nothing else changed. Built only
# when asked for (--target test).
FROM stationplay AS test
RUN pip install --no-cache-dir pytest==9.1.1 pytest-asyncio==1.4.0
COPY pytest.ini pyproject.toml stationplay.yaml docker-compose.yml ./
COPY docs ./docs
COPY tools/openapi_spec.py ./tools/
COPY tests ./tests
RUN chmod -R a+rX pytest.ini pyproject.toml stationplay.yaml docker-compose.yml docs tools tests
USER 1000:1000
HEALTHCHECK NONE
CMD ["python", "-m", "pytest", "-v", "-p", "no:cacheprovider", "-rfE"]

# What's built by default, and ships: the image above, without the tests.
FROM stationplay
