#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}"

if [[ ! -f "${REPO_ROOT}/tailwind.config.js" ]]; then
    echo "tailwind.config.js not found in ${REPO_ROOT}" >&2
    exit 1
fi

echo "Building Tailwind CSS..."
"${REPO_ROOT}/tailwindcss-linux-x64" \
    -c "${REPO_ROOT}/tailwind.config.js" \
    -i "${REPO_ROOT}/app/static/css/tailwind-src.css" \
    -o "${REPO_ROOT}/app/static/css/tailwind.css" \
    --minify
echo "Tailwind CSS build complete."
