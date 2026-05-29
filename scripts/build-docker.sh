#!/usr/bin/env bash
# Build and optionally push estampo Docker images.
#
# Usage:
#   ./scripts/build-docker.sh orca-base 2.3.1       # build orca-base image
#   ./scripts/build-docker.sh orca-base 2.3.1 --push
#   ./scripts/build-docker.sh slicer 2.3.1           # build OrcaSlicer estampo image
#   ./scripts/build-docker.sh slicer 2.3.1 --push
#   ./scripts/build-docker.sh cura-base 5.12.0       # build cura-base image
#   ./scripts/build-docker.sh cura-base 5.12.0 --push
#   ./scripts/build-docker.sh cura-slicer 5.12.0     # build CuraEngine estampo image
#   ./scripts/build-docker.sh cura-slicer 5.12.0 --push
#
# Legacy (orca slicer only):
#   ./scripts/build-docker.sh 2.3.1          # build slicer image
#   ./scripts/build-docker.sh 2.3.1 --push

set -euo pipefail

TARGET="${1:?Usage: $0 <orca-base|slicer|orca-version> [version] [--push]}"

case "$TARGET" in
    orca-base)
        VERSION="${2:?Usage: $0 orca-base <orca-version> [--push]}"
        PUSH="${3:-}"
        IMAGE="estampo/orca-base:${VERSION}"

        echo "Building ${IMAGE} ..."
        docker build \
            --platform linux/amd64 \
            -f Dockerfile.orca-base \
            --build-arg "ORCA_VERSION=${VERSION}" \
            -t "${IMAGE}" \
            .

        echo "Tagging as estampo/orca-base:latest ..."
        docker tag "${IMAGE}" estampo/orca-base:latest
        echo "Build complete: ${IMAGE}"

        if [ "${PUSH}" = "--push" ]; then
            docker push "${IMAGE}"
            docker push estampo/orca-base:latest
            echo "Pushed."
        fi
        ;;

    slicer)
        VERSION="${2:?Usage: $0 slicer <orca-version> [--push]}"
        PUSH="${3:-}"
        IMAGE="estampo/estampo:orca-${VERSION}"

        echo "Building ${IMAGE} ..."
        docker build \
            --platform linux/amd64 \
            --build-arg "ORCA_VERSION=${VERSION}" \
            -t "${IMAGE}" \
            .

        echo "Tagging as estampo/estampo:latest ..."
        docker tag "${IMAGE}" estampo/estampo:latest
        echo "Build complete: ${IMAGE}"

        if [ "${PUSH}" = "--push" ]; then
            docker push "${IMAGE}"
            docker push estampo/estampo:latest
            echo "Pushed."
        fi
        ;;

    cura-base)
        VERSION="${2:?Usage: $0 cura-base <cura-version> [--push]}"
        PUSH="${3:-}"
        IMAGE="estampo/cura-base:${VERSION}"

        echo "Building ${IMAGE} ..."
        docker build \
            --platform linux/amd64 \
            -f Dockerfile.cura-base \
            --build-arg "CURA_VERSION=${VERSION}" \
            -t "${IMAGE}" \
            .

        echo "Tagging as estampo/cura-base:latest ..."
        docker tag "${IMAGE}" estampo/cura-base:latest
        echo "Build complete: ${IMAGE}"

        if [ "${PUSH}" = "--push" ]; then
            docker push "${IMAGE}"
            docker push estampo/cura-base:latest
            echo "Pushed."
        fi
        ;;

    cura-slicer)
        VERSION="${2:?Usage: $0 cura-slicer <cura-version> [--push]}"
        PUSH="${3:-}"
        IMAGE="estampo/estampo:cura-${VERSION}"

        echo "Building ${IMAGE} ..."
        docker build \
            --platform linux/amd64 \
            -f Dockerfile.cura \
            --build-arg "CURA_VERSION=${VERSION}" \
            -t "${IMAGE}" \
            .

        echo "Build complete: ${IMAGE}"

        if [ "${PUSH}" = "--push" ]; then
            docker push "${IMAGE}"
            echo "Pushed."
        fi
        ;;

    *)
        # Legacy: treat first arg as OrcaSlicer version
        VERSION="$TARGET"
        PUSH="${2:-}"
        IMAGE="estampo/estampo:orca-${VERSION}"

        echo "Building ${IMAGE} ..."
        docker build \
            --platform linux/amd64 \
            --build-arg "ORCA_VERSION=${VERSION}" \
            -t "${IMAGE}" \
            .

        echo "Tagging as estampo/estampo:latest ..."
        docker tag "${IMAGE}" estampo/estampo:latest
        echo "Build complete: ${IMAGE}"

        if [ "${PUSH}" = "--push" ]; then
            docker push "${IMAGE}"
            docker push estampo/estampo:latest
            echo "Pushed."
        fi
        ;;
esac
