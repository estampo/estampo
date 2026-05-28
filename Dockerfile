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
# Main image
# ---------------------------------------------------------------------------
FROM estampo/orca-base:${ORCA_VERSION}

ARG BAMBOX_VERSION=0.6.1

LABEL org.opencontainers.image.description="estampo with OrcaSlicer ${ORCA_VERSION}"

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
