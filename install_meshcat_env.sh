#!/usr/bin/env bash
set -euo pipefail

# One-click dependency installer for demo/meshcat/piper_web.py.
# It intentionally does not install legacy demo/PICO-only dependencies.

ENV_NAME="${ENV_NAME:-robotarm}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
MINIFORGE_DIR="${MINIFORGE_DIR:-$HOME/miniforge3}"
AUTO_INSTALL_CONDA="${AUTO_INSTALL_CONDA:-1}"

CONDA_PACKAGES=(
  "numpy"
  "scipy"
  "pinocchio"
  "transforms3d"
  "meshcat-python"
)

PIP_PACKAGES=(
  "paho-mqtt"
  "python-can"
  "piper-sdk"
  "typing-extensions"
)

log() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*" >&2
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

sudo_run() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif have_cmd sudo; then
    sudo "$@"
  else
    die "sudo is required to install system packages."
  fi
}

detect_conda() {
  if have_cmd conda; then
    command -v conda
    return 0
  fi

  for candidate in \
    "$HOME/miniforge3/bin/conda" \
    "$HOME/miniconda3/bin/conda" \
    "$HOME/anaconda3/bin/conda" \
    "/opt/miniforge3/bin/conda" \
    "/opt/miniconda3/bin/conda" \
    "/opt/anaconda3/bin/conda" \
    "/usr/local/miniforge3/bin/conda" \
    "/usr/local/miniconda3/bin/conda" \
    "/usr/local/anaconda3/bin/conda"; do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

download_miniforge() {
  local arch installer url
  arch="$(uname -m)"
  case "$arch" in
    x86_64|aarch64|ppc64le) ;;
    arm64) arch="aarch64" ;;
    *) die "Unsupported CPU architecture for automatic Miniforge install: $arch" ;;
  esac

  installer="${TMPDIR:-/tmp}/Miniforge3-Linux-${arch}.sh"
  url="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-${arch}.sh"

  log "Downloading Miniforge from $url"
  if have_cmd curl; then
    curl -fsSL "$url" -o "$installer"
  elif have_cmd wget; then
    wget -q "$url" -O "$installer"
  else
    die "curl or wget is required to download Miniforge."
  fi

  log "Installing Miniforge to $MINIFORGE_DIR"
  bash "$installer" -b -p "$MINIFORGE_DIR"
  rm -f "$installer"
}

install_system_packages() {
  if have_cmd apt-get; then
    log "Installing system packages for SocketCAN and setup tools"
    sudo_run apt-get update
    sudo_run apt-get install -y \
      ca-certificates \
      curl \
      wget \
      bash \
      sudo \
      grep \
      gawk \
      can-utils \
      ethtool \
      iproute2 \
      kmod
  else
    log "apt-get not found; skipping system package install."
    log "Make sure these commands/packages exist: bash, sudo, grep, awk, ip, ethtool, can-utils, modprobe."
  fi
}

ensure_conda() {
  local conda_exe
  if conda_exe="$(detect_conda)"; then
    printf '%s\n' "$conda_exe"
    return 0
  fi

  if [ "$AUTO_INSTALL_CONDA" != "1" ]; then
    die "Conda was not found. Install Miniforge/Miniconda, or run with AUTO_INSTALL_CONDA=1."
  fi

  download_miniforge
  [ -x "$MINIFORGE_DIR/bin/conda" ] || die "Miniforge install finished but conda was not found."
  printf '%s\n' "$MINIFORGE_DIR/bin/conda"
}

conda_env_exists() {
  "$CONDA_EXE" env list | awk '{print $1}' | grep -Fxq "$ENV_NAME"
}

install_python_packages() {
  if conda_env_exists; then
    log "Updating existing conda environment: $ENV_NAME"
  else
    log "Creating conda environment: $ENV_NAME (Python $PYTHON_VERSION)"
    "$CONDA_EXE" create -y -n "$ENV_NAME" "python=$PYTHON_VERSION"
  fi

  log "Installing conda packages: ${CONDA_PACKAGES[*]}"
  "$CONDA_EXE" install -y -n "$ENV_NAME" -c conda-forge "${CONDA_PACKAGES[@]}"

  log "Installing pip packages: ${PIP_PACKAGES[*]}"
  "$CONDA_EXE" run -n "$ENV_NAME" python -m pip install --upgrade pip
  "$CONDA_EXE" run -n "$ENV_NAME" python -m pip install --upgrade "${PIP_PACKAGES[@]}"
}

run_import_check() {
  log "Running import check"
  "$CONDA_EXE" run -n "$ENV_NAME" python - <<'PY'
import numpy
import scipy
import transforms3d
import pinocchio
import meshcat
import paho.mqtt.client
import can
import piper_sdk
import typing_extensions
from pinocchio.visualize import MeshcatVisualizer
print("meshcat piper_web dependencies OK")
PY
}

main() {
  case "$(uname -s)" in
    Linux) ;;
    *) die "This installer targets Linux/Ubuntu because piper_web.py uses SocketCAN." ;;
  esac

  install_system_packages

  CONDA_EXE="$(ensure_conda)"
  export CONDA_EXE
  log "Using conda: $CONDA_EXE"

  install_python_packages
  run_import_check

  log "Done."
  local conda_base
  conda_base="$("$CONDA_EXE" info --base)"
  printf '\nRun the controller with:\n'
  printf '  source "%s/etc/profile.d/conda.sh"\n' "$conda_base"
  printf '  conda activate %s\n' "$ENV_NAME"
  printf '  python demo/meshcat/piper_web.py\n'
  printf '\nOr use:\n'
  printf '  bash piper.sh\n'
}

main "$@"
