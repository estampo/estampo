#!/usr/bin/env bash
# Install the latest dev build of fabprint from TestPyPI.
# Usage: ./scripts/install-test.sh
set -euo pipefail

pip install --upgrade --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ \
    --pre fabprint

echo ""
fabprint --version
