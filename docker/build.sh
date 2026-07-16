#!/usr/bin/env bash
#
# 建立 CareerStatic Docker image。

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

docker compose -f "${SCRIPT_DIR}/docker-compose.yaml" build "$@"
