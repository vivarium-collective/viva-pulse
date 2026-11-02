#!/usr/bin/env bash
# Build the Pulse engine from source into $BUILD_DIR/install, then verify it.
#
# The configure flags are the ones in .build-progress.md ("Build workarounds"):
# Pulse's CMake ignores -DPython3_EXECUTABLE, so the venv is selected with
# -DPulse_PYTHON_HOME_DIR plus VIRTUAL_ENV. The build pip-installs protobuf
# into that venv, so it must have been created with `uv venv --seed`.
#
# Usage: ENGINE_DIR=engine VENV=.venv BUILD_DIR=.pulse-build build-pulse.sh
set -euo pipefail

: "${ENGINE_DIR:?path to the Pulse engine checkout}"
: "${VENV:?path to the venv PyPulse is built against}"
: "${BUILD_DIR:?path to the CMake build directory}"

ENGINE_DIR=$(cd "$ENGINE_DIR" && pwd)
VENV=$(cd "$VENV" && pwd)
mkdir -p "$BUILD_DIR"
BUILD_DIR=$(cd "$BUILD_DIR" && pwd)
JOBS=${JOBS:-$(nproc 2>/dev/null || sysctl -n hw.ncpu)}

export VIRTUAL_ENV="$VENV"
cmake --fresh -S "$ENGINE_DIR" -B "$BUILD_DIR" \
  -DCMAKE_BUILD_TYPE:STRING=Release \
  -DCMAKE_C_COMPILER="${CC:-clang}" -DCMAKE_CXX_COMPILER="${CXX:-clang++}" \
  -DPulse_PYTHON_HOME_DIR="$VENV" \
  -DPython3_FIND_VIRTUALENV=ONLY \
  -DPulse_JAVA_API=ON -DPulse_PYTHON_API=ON -DPulse_GEN_DATA=ON
cmake --build "$BUILD_DIR" -j "$JOBS"

# Data generation failures and a missing Java only warn, so a build can
# "succeed" with no state files. Never let such an install be cached.
"$VENV/bin/python" "$(dirname "$0")/verify-pulse-install.py" "$BUILD_DIR/install"
