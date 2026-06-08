#!/usr/bin/env bash
# Build the Docker-free Lambda deployment package.
#
# Vendors Linux/arm64 (Graviton) wheels for the runtime deps and bundles the
# app code into build/lambda_package, which the Amplify backend ships as a zip
# asset (lambda.Code.fromAsset). No Docker required.
#
# boto3 is intentionally NOT vendored — the Lambda runtime already provides it.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKG="$ROOT/build/lambda_package"
PY="${PYTHON:-$ROOT/.venv/bin/python}"

echo "Building Lambda package → $PKG"
rm -rf "$PKG"
mkdir -p "$PKG"

# Linux arm64 wheels for the Lambda python3.10 runtime.
# 3.10 (not 3.11+) because alpaca-trade-api pins old exact deps — websockets<11
# and msgpack==1.0.3 — whose newest arm64 wheels stop at cp310. 3.10 is the
# highest runtime with prebuilt wheels for the entire dependency tree.
"$PY" -m pip install \
  --platform manylinux2014_aarch64 \
  --implementation cp \
  --python-version 3.10 \
  --only-binary=:all: \
  --target "$PKG" \
  --upgrade \
  -r "$ROOT/requirements-lambda.txt"

# App code.
cp -r "$ROOT/src" "$PKG/src"
cp "$ROOT/lambda_fns/"*.py "$PKG/"
mkdir -p "$PKG/config"
cp "$ROOT/config/settings.yaml" "$PKG/config/settings.yaml"

# Trim caches to shrink the asset.
find "$PKG" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "$PKG" -type d -name 'tests' -prune -exec rm -rf {} + 2>/dev/null || true

echo "Done."
du -sh "$PKG"
