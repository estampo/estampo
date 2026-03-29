#!/usr/bin/env bash
# Build and optionally push estampo Docker images.
#
# Usage:
#   ./scripts/build-docker.sh orca-base 2.3.1       # build orca-base image
#   ./scripts/build-docker.sh orca-base 2.3.1 --push
#   ./scripts/build-docker.sh slicer 2.3.1           # build slicer image
#   ./scripts/build-docker.sh slicer 2.3.1 --push
#   ./scripts/build-docker.sh cloud-bridge           # build cloud bridge image
#   ./scripts/build-docker.sh cloud-bridge --push
#
# Legacy (slicer only):
#   ./scripts/build-docker.sh 2.3.1          # build slicer image
#   ./scripts/build-docker.sh 2.3.1 --push

set -euo pipefail

TARGET="${1:?Usage: $0 <orca-base|slicer|cloud-bridge|orca-version> [version] [--push]}"

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

    cloud-bridge)
        PUSH="${2:-}"
        IMAGE="estampo/cloud-bridge:latest"
        BNL_TOKEN="${BNL_TOKEN:-$(gh auth token 2>/dev/null || true)}"

        echo "Building ${IMAGE} ..."
        docker build \
            --platform linux/amd64 \
            -f Dockerfile.cloud-bridge \
            --build-arg "BNL_TOKEN=${BNL_TOKEN}" \
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
