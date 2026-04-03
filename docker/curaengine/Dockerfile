# CuraEngine Docker image for estampo
#
# Extracts CuraEngine and its dependencies from the UltiMaker Cura AppImage.
# This produces a minimal (~95 MB) image with just the slicer engine and
# printer definitions — no GUI, no Python, no Qt.
#
# Build:
#   docker build -t estampo/curaengine:5.12.0 docker/curaengine/
#
# Usage:
#   docker run --rm estampo/curaengine:5.12.0 help
#   docker run --rm -v $(pwd):/work estampo/curaengine:5.12.0 \
#     slice -j /opt/cura/definitions/fdmprinter.def.json \
#     -o /work/output.gcode -s layer_height=0.2 -l /work/model.stl

ARG CURA_VERSION=5.12.0
ARG CURA_APPIMAGE_URL=https://github.com/Ultimaker/Cura/releases/download/${CURA_VERSION}/UltiMaker-Cura-${CURA_VERSION}-linux-X64.AppImage

# --- Stage 1: Extract from AppImage ---
FROM ubuntu:24.04 AS extract

ARG CURA_APPIMAGE_URL

RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /extract
RUN curl -fsSL -o cura.AppImage "${CURA_APPIMAGE_URL}" \
    && chmod +x cura.AppImage \
    && ./cura.AppImage --appimage-extract \
    && rm cura.AppImage

# --- Stage 2: Minimal runtime image ---
FROM ubuntu:24.04

LABEL org.opencontainers.image.title="CuraEngine for estampo"
LABEL org.opencontainers.image.description="CuraEngine slicer extracted from UltiMaker Cura AppImage"
LABEL org.opencontainers.image.source="https://github.com/estampo/estampo"
LABEL org.opencontainers.image.licenses="AGPL-3.0"

# CuraEngine binary
COPY --from=extract /extract/squashfs-root/CuraEngine /usr/local/bin/CuraEngine

# Bundled shared libraries (not available in ubuntu:24.04)
COPY --from=extract /extract/squashfs-root/libArcus.so /usr/local/lib/
COPY --from=extract /extract/squashfs-root/libpolyclipping.so.22.0.0 /usr/local/lib/
COPY --from=extract /extract/squashfs-root/libtbb.so.12.16 /usr/local/lib/
COPY --from=extract /extract/squashfs-root/libtbbmalloc.so.2.16 /usr/local/lib/
COPY --from=extract /extract/squashfs-root/libtbbmalloc_proxy.so.2.16 /usr/local/lib/
COPY --from=extract /extract/squashfs-root/libssl.so.3 /usr/local/lib/libssl.so.3.cura
COPY --from=extract /extract/squashfs-root/libcrypto.so.3 /usr/local/lib/libcrypto.so.3.cura

# Symlinks for versioned libraries
RUN cd /usr/local/lib \
    && ln -sf libpolyclipping.so.22.0.0 libpolyclipping.so.22 \
    && ln -sf libtbb.so.12.16 libtbb.so.12 \
    && ln -sf libtbbmalloc.so.2.16 libtbbmalloc.so.2 \
    && ln -sf libtbbmalloc_proxy.so.2.16 libtbbmalloc_proxy.so.2 \
    && ln -sf libssl.so.3.cura libssl.so.3 \
    && ln -sf libcrypto.so.3.cura libcrypto.so.3 \
    && ldconfig \
    && chmod +x /usr/local/bin/CuraEngine

# Printer definitions (fdmprinter.def.json, fdmextruder.def.json, etc.)
COPY --from=extract /extract/squashfs-root/share/cura/resources/definitions/ /opt/cura/definitions/
COPY --from=extract /extract/squashfs-root/share/cura/resources/extruders/ /opt/cura/extruders/

ENV CURA_ENGINE_SEARCH_PATH=/opt/cura/definitions:/opt/cura/extruders

ENTRYPOINT ["CuraEngine"]
