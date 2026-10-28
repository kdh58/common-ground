#!/usr/bin/env bash
# Build the real Dockerfile; mount tests only, never substitute host application code.
set -euo pipefail
cd "$(dirname "$0")/.."
scheduling_test_image=${CG_TEST_IMAGE:-cg-timezone-test:local}
docker build --tag "$scheduling_test_image" .
docker run --rm --network none \
  --mount "type=bind,src=$PWD/tests,dst=/project/tests,readonly" \
  "$scheduling_test_image" python -m pytest -q -p no:cacheprovider tests/test_timezone_database.py
