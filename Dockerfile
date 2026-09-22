# syntax=docker/dockerfile:1
FROM python:3.12-slim-trixie@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9 AS source
ARG UPSTREAM_COMMIT=2bcb98d1a8b6fe05e15fbc1559e3085669e4035d
ADD --checksum=sha256:d901d1e20f6a238830abff268ae5d8d60448b34b7ef0e65d9f0f88a10f1ee083 https://codeload.github.com/jamiepine/voicebox/tar.gz/2bcb98d1a8b6fe05e15fbc1559e3085669e4035d /source.tar.gz
RUN test "$UPSTREAM_COMMIT" = 2bcb98d1a8b6fe05e15fbc1559e3085669e4035d && mkdir /source && tar -xzf /source.tar.gz -C /source --strip-components=1

FROM oven/bun:1@sha256:9114c058aeae42162ee16dd5084b95fe9473970bb6bcb5b232ab1630f0546895 AS frontend
WORKDIR /build
COPY --from=source /source/package.json /source/bun.lock /source/CHANGELOG.md ./
COPY --from=source /source/app ./app
COPY --from=source /source/web ./web
# Match upstream's web-only workspace selection.
RUN sed -i '/"tauri"/d; /"landing"/d' package.json && sed -i -z 's/,\n  ]/\n  ]/' package.json
RUN bun install --no-save
ARG UPSTREAM_VERSION=0.5.0
RUN cd web && VITE_APP_VERSION="$UPSTREAM_VERSION" bunx --bun vite build

FROM python:3.12-slim-trixie@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9 AS dependencies
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential cmake pkg-config libsndfile1-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.lock /build/requirements.lock
RUN pip install --no-cache-dir --prefix=/install -r /build/requirements.lock
# Upstream installs these without dependency resolution because of conflicting torch pins.
RUN pip install --no-cache-dir --prefix=/install --no-deps chatterbox-tts==0.1.7 hume-tada==0.1.9

FROM python:3.12-slim-trixie@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9
ARG UPSTREAM_VERSION=0.5.0
ARG UPSTREAM_COMMIT=2bcb98d1a8b6fe05e15fbc1559e3085669e4035d
ARG PACKAGING_REVISION=3
LABEL org.opencontainers.image.source="https://github.com/MichaelSchmidle/voicebox-container" \
      org.opencontainers.image.version="${UPSTREAM_VERSION}-r${PACKAGING_REVISION}" \
      org.opencontainers.image.revision="$UPSTREAM_COMMIT" \
      org.opencontainers.image.licenses="MIT"
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 libgomp1 libatomic1 sox && rm -rf /var/lib/apt/lists/* && groupadd -g 10001 voicebox && useradd -u 10001 -g voicebox -m voicebox
COPY --from=dependencies /install /usr/local
WORKDIR /app
COPY --from=source --chown=10001:10001 /source/backend /app/backend
COPY --from=source /source/LICENSE /usr/share/licenses/voicebox/LICENSE
COPY --from=frontend --chown=10001:10001 /build/web/dist /app/frontend
RUN mkdir -p /app/data/generations /app/data/profiles /app/data/cache && chown -R 10001:10001 /app/data
ENV HF_HOME=/app/data/cache/huggingface NUMBA_CACHE_DIR=/tmp/numba_cache
USER 10001:10001
EXPOSE 17493
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:17493/health', timeout=5).close()"]
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "17493"]
