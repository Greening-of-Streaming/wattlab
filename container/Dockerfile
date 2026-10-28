# OWL (Online WattLab) — container image.
#
# Build from the REPO ROOT (the context needs wattlab_service/):
#   docker build -f container/Dockerfile -t owl .                          # CUDA torch (GPU hosts)
#   docker build -f container/Dockerfile --build-arg TORCH_FLAVOUR=cpu -t owl:cpu .   # CPU-only, ~3 GB smaller
#
# Normally driven by container/docker-compose.yml — see container/README.md.
FROM ubuntu:24.04

ARG TORCH_FLAVOUR=cu128
ARG TORCH_VERSION=2.11.0
# Static FFmpeg with NVENC + libvmaf (BtbN GPL build, n8.1 release branch).
# The exact build is recorded in /opt/owl/ffmpeg.version and on /settings.
ARG FFMPEG_URL=https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n8.1-latest-linux64-gpl-8.1.tar.xz

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OWL_ROOT=/app \
    HF_HOME=/data/hf \
    NVIDIA_DRIVER_CAPABILITIES=compute,video,utility

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip ca-certificates curl xz-utils \
        lm-sensors git tini \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "$FFMPEG_URL" -o /tmp/ffmpeg.tar.xz \
    && mkdir -p /opt/ffmpeg && tar -xJf /tmp/ffmpeg.tar.xz -C /opt/ffmpeg --strip-components=1 \
    && ln -s /opt/ffmpeg/bin/ffmpeg /usr/local/bin/ffmpeg \
    && ln -s /opt/ffmpeg/bin/ffprobe /usr/local/bin/ffprobe \
    && rm /tmp/ffmpeg.tar.xz \
    && mkdir -p /opt/owl && ffmpeg -hide_banner -version | head -1 > /opt/owl/ffmpeg.version \
    && ffmpeg -hide_banner -filters | grep -q libvmaf

RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

COPY requirements.txt /tmp/requirements.txt
# torch first, from the flavour's index; the pinned +cu128 line in
# requirements.txt is GoS1's and is skipped here. The constraint then pins the
# installed torch, so a dependency conflict fails the build instead of pip
# silently swapping in a different (CUDA) torch from PyPI.
RUN pip install "torch==${TORCH_VERSION}" --index-url "https://download.pytorch.org/whl/${TORCH_FLAVOUR}" \
    && pip freeze | grep '^torch==' > /tmp/torch-constraint.txt \
    && grep -v '^torch==' /tmp/requirements.txt > /tmp/req-notorch.txt \
    && pip install -r /tmp/req-notorch.txt -c /tmp/torch-constraint.txt

WORKDIR /app
COPY VERSION LICENSE ./
COPY wattlab_service ./wattlab_service
COPY docs/findings ./docs/findings
COPY container ./container

# version.json stands in for `git describe` (no .git in the image).
ARG OWL_GIT_SHA=unknown
RUN printf '{"sha": "%s", "dirty": false, "built_at": "%s", "source": "container"}\n' \
        "$OWL_GIT_SHA" "$(date -u +%Y-%m-%d)" > /app/version.json \
    && chmod +x /app/container/entrypoint.sh /app/container/fetch_test_content.sh

EXPOSE 8000
VOLUME ["/data"]
ENTRYPOINT ["/usr/bin/tini", "--", "/app/container/entrypoint.sh"]
CMD ["serve"]
