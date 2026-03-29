#!/usr/bin/env bash
# Install the latest dev build of estampo from TestPyPI.
# Usage: ./scripts/install-test.sh
set -euo pipefail

# Find the latest dev version from the TestPyPI JSON API
LATEST=$(python3 -c "
import json, urllib.request
data = json.load(urllib.request.urlopen('https://test.pypi.org/pypi/estampo/json'))
devs = [v for v in data['releases'] if '.dev' in v]
devs.sort(key=lambda v: data['releases'][v][0]['upload_time'] if data['releases'][v] else '')
print(devs[-1])
")

if [ -z "$LATEST" ]; then
    echo "Could not find a dev version on TestPyPI"
    exit 1
fi

echo "Installing estampo==${LATEST} from TestPyPI..."
pip install --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ \
    "estampo==${LATEST}"

echo ""
estampo --version
