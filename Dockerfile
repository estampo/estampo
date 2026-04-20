# estampo: layers Python package on top of orca-base image
#
# The base image (estampo/orca-base) contains OrcaSlicer + runtime deps and
# changes only on OrcaSlicer version bumps. This Dockerfile just installs the
# Python package, so code-only rebuilds are fast (~10s).
#
# Usage:
#   docker build --build-arg ORCA_VERSION=2.3.1 -t estampo/estampo:orca-2.3.1 .
#   docker run --rm -v "$PWD:/project" estampo/estampo:orca-2.3.1 run estampo.toml

ARG ORCA_VERSION=2.3.1

# ---------------------------------------------------------------------------
# Fetch stage: bambox-bridge binary + libbambu_networking.so + TLS cert
# ---------------------------------------------------------------------------
FROM --platform=linux/amd64 debian:bookworm-slim AS bridge-fetcher

ARG BAMBOX_VERSION=0.4.5
ARG BAMBU_SLICER_VERSION=02.05.00.00
ARG BNL_TOKEN=""

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl python3 unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Download pre-built bambox-bridge binary from GitHub release
RUN curl -fSL -o /usr/local/bin/bambox-bridge \
        "https://github.com/estampo/bambox/releases/download/v${BAMBOX_VERSION}/bambox-bridge-linux-x86_64" \
    && chmod +x /usr/local/bin/bambox-bridge

# Fetch libbambu_networking.so (Bambu API → private cache fallback)
RUN mkdir -p /out/lib /out/cert \
    && (PLUGIN_URL=$(curl -fsSL \
        -H "User-Agent: BambuStudio/${BAMBU_SLICER_VERSION}" \
        -H "X-BBL-OS-Type: linux" \
        "https://api.bambulab.com/v1/iot-service/api/slicer/resource?slicer/plugins/cloud=${BAMBU_SLICER_VERSION}" \
        | python3 -c "import sys,json; r=json.load(sys.stdin)['resources']; print([x for x in r if 'plugins' in x['type']][0]['url'])") \
    && curl -fsSL -o /tmp/plugins.zip "$PLUGIN_URL" \
    && unzip -j /tmp/plugins.zip libbambu_networking.so -d /out/lib/ \
    && echo "Fetched libbambu_networking.so from Bambu API") \
    || (echo "Bambu API failed, falling back to private cache..." \
    && curl -fsSL \
        -H "Authorization: token ${BNL_TOKEN}" \
        -H "Accept: application/octet-stream" \
        -o /out/lib/libbambu_networking.so \
        "https://api.github.com/repos/estampo/bnl/releases/assets/$(curl -fsSL \
            -H "Authorization: token ${BNL_TOKEN}" \
            "https://api.github.com/repos/estampo/bnl/releases/tags/v${BAMBU_SLICER_VERSION}" \
            | python3 -c "import sys,json; print([a for a in json.load(sys.stdin)['assets'] if a['name']=='libbambu_networking.so'][0]['id'])")" \
    && echo "Fetched libbambu_networking.so from private cache")

# TLS certificate for Bambu Cloud MQTT
RUN curl -fSL -o /out/cert/slicer_base64.cer \
       "https://raw.githubusercontent.com/bambulab/BambuStudio/master/resources/cert/slicer_base64.cer"

# ---------------------------------------------------------------------------
# Main image
# ---------------------------------------------------------------------------
FROM estampo/orca-base:${ORCA_VERSION}

ARG BAMBOX_VERSION=0.4.5

LABEL org.opencontainers.image.description="estampo with OrcaSlicer ${ORCA_VERSION}"

# bambox-bridge + libbambu_networking.so + TLS cert
COPY --from=bridge-fetcher /usr/local/bin/bambox-bridge /usr/local/bin/bambox-bridge
COPY --from=bridge-fetcher /out/lib/libbambu_networking.so /usr/lib/libbambu_networking.so
COPY --from=bridge-fetcher /out/cert/slicer_base64.cer /tmp/bambu_agent/cert/slicer_base64.cer
ENV BAMBU_LIB_PATH=/usr/lib/libbambu_networking.so

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install dependencies first (cached unless lockfile changes)
WORKDIR /opt/estampo
COPY pyproject.toml uv.lock README.md LICENSE ./
# Stub so hatchling can discover the package during dep install
RUN mkdir -p src/estampo && touch src/estampo/__init__.py
RUN --mount=type=cache,target=/root/.cache/uv \
    uv python install 3.12 \
    && uv sync --frozen --no-dev --no-editable --python 3.12 \
    && chmod -R a+rX /home/estampo/.local/share/uv/python

# Copy source and re-link (fast — deps already installed)
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --python 3.12

# orca-base sets HOME=/home/estampo, so uv (running as root) installs the
# managed Python under /home/estampo/.local/... Without these chmods the
# estampo runtime user can't traverse the path or read python-build-standalone's
# relocation data, so Python falls back to its hardcoded /install prefix and
# breaks any command stage that invokes Python (e.g. bambox repack). Every
# directory on the traversal path — including /home/estampo itself — must be
# a+rx (compare Dockerfile.cura which chmods /root the same way). See #641.
RUN chmod a+rx /home/estampo /home/estampo/.local /home/estampo/.local/share \
    /home/estampo/.local/share/uv /home/estampo/.local/share/uv/python

# Install bambox (CLI-only tool for Bambu Lab printers — not an estampo
# dependency, but bundled so command stages like `bambox repack` work
# inside the container without requiring host-side installation).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install "bambox==${BAMBOX_VERSION}" --python /opt/estampo/.venv/bin/python

ENV PATH="/opt/estampo/.venv/bin:$PATH"

USER estampo
WORKDIR /project
ENTRYPOINT ["estampo"]
CMD ["--help"]
