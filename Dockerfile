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
FROM estampo/orca-base:${ORCA_VERSION}

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
    && uv sync --frozen --no-dev --no-editable --python 3.12

# Copy source and re-link (fast — deps already installed)
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --python 3.12

ENV PATH="/opt/estampo/.venv/bin:$PATH"

USER estampo
WORKDIR /project
ENTRYPOINT ["estampo"]
CMD ["--help"]
