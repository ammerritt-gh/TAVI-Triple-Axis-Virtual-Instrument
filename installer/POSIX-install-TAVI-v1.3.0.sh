#!/bin/bash
#
# TAVI POSIX installer - release-pinned v1.3.0
#
# PROVISIONAL: written 2026-09-14 and never executed on macOS or Linux by the
# maintainer. This mirrors installer/WINDOWS-install-TAVI-v1.3.0.bat step by
# step but has no platform coverage of its own yet.
#
# If it fails, stop at the first failure and paste the whole terminal output
# into an issue at
# https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/issues
# with the label platform-installer. Do not debug it yourself.
#
# What a partial run may leave behind:
#   $HOME/.local/bin/micromamba  (only if this script installed it)
#   $HOME/micromamba             (root prefix, with an env named tavi)
#   $HOME/TAVI
# The uninstaller (POSIX-uninstall-TAVI.sh) removes the env and the folder.

set -euo pipefail

TAVI_VERSION="v1.3.0"
INSTALLER_VERSION="v1.3.0"
PYTHON_VERSION="3.11"
MCSTAS_VERSION="3.7.1"
MAMBA_VERSION="2.5.0-1"
REPO_URL="https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument.git"
INSTALL_DIR="$HOME/TAVI"
MAMBA_ROOT_PREFIX="$HOME/micromamba"
ENV_NAME=tavi

# verify_sha256 <file> <expected-sha256>
# Extracted as its own function so it can be sourced and exercised directly
# without running the rest of the installer (see the guard at the bottom).
verify_sha256() {
    local file expected actual
    file="$1"
    expected="$2"
    if command -v sha256sum >/dev/null 2>&1; then
        actual=$(sha256sum "$file" | awk '{print $1}')
    else
        actual=$(shasum -a 256 "$file" | awk '{print $1}')
    fi
    [ "$actual" = "$expected" ]
}

unsupported_platform() {
    echo "unsupported platform ${OS:-}/${ARCH:-}; this installer supports macOS 12+ (x86_64, arm64) and glibc Linux (x86_64, aarch64)" >&2
    exit 1
}

main() {
    local os arch mamba_asset mamba_sha256
    local downloader sdk_path reply
    local micromamba_exe env_prefix conda_packages backup_dir broken_backup
    local mcstas_resources mcrun progress_bar tmp_cfg pb_map pb_map_file
    local run_script command_script update_script

    # --- Step 1: platform detection ---------------------------------------
    os=$(uname -s)
    arch=$(uname -m)
    OS="$os"
    ARCH="$arch"

    case "$os" in
        Darwin)
            case "$arch" in
                x86_64) mamba_asset=micromamba-osx-64 ;;
                arm64) mamba_asset=micromamba-osx-arm64 ;;
                *) unsupported_platform ;;
            esac
            ;;
        Linux)
            case "$arch" in
                x86_64) mamba_asset=micromamba-linux-64 ;;
                aarch64) mamba_asset=micromamba-linux-aarch64 ;;
                *) unsupported_platform ;;
            esac
            if command -v ldd >/dev/null 2>&1; then
                if ldd --version 2>&1 | grep -qi musl; then
                    echo "unsupported platform $os/$arch (musl libc); this installer supports glibc Linux only" >&2
                    exit 1
                fi
            fi
            ;;
        *)
            unsupported_platform
            ;;
    esac

    case "$mamba_asset" in
        micromamba-linux-64) mamba_sha256=dd9899873602972ae3b9ec02fc11b2fb1ab51f5eab5eacdf23ef385313f22491 ;;
        micromamba-linux-aarch64) mamba_sha256=534dd24fb57a8b72a79b883d69b959d7f1c7958be9918be9ddd907a0ffdfdf0e ;;
        micromamba-osx-64) mamba_sha256=dc7e924d87d4c4c28bfa09e54c1115779099140c411a2766a8e617d8be285501 ;;
        micromamba-osx-arm64) mamba_sha256=1fb48de51d18d07b224ea2bf8d6b3b2e3262512affbcb7e8c0e3fe64b46f3e76 ;;
    esac

    # --- Step 2: preflight ---------------------------------------------------
    if command -v curl >/dev/null 2>&1; then
        downloader=curl
    elif command -v wget >/dev/null 2>&1; then
        downloader=wget
    else
        echo "no downloader found: install curl or wget and re-run" >&2
        exit 1
    fi

    if [ "$os" = "Darwin" ]; then
        if ! xcode-select -p >/dev/null 2>&1; then
            echo "Xcode command line tools not found. Run: xcode-select --install" >&2
            exit 1
        fi
        sdk_path=$(xcrun --sdk macosx --show-sdk-path 2>/dev/null) || sdk_path=""
        if [ -z "$sdk_path" ] || [ ! -d "$sdk_path" ]; then
            echo "macOS SDK not found. Run: xcode-select --install" >&2
            exit 1
        fi
    fi

    # --- Step 3: explanation and confirmation --------------------------------
    cat <<EOF
============================================================================
                    TAVI POSIX Installer
                 Triple Axis Virtual Instrument
                 Release: $TAVI_VERSION
============================================================================
Installer version: $INSTALLER_VERSION
TAVI version:      $TAVI_VERSION
Python version:    $PYTHON_VERSION
McStas version:    $MCSTAS_VERSION
Micromamba:        $MAMBA_VERSION

PROVISIONAL: written 2026-09-14 and never executed on macOS or Linux by the
maintainer. If it fails, stop at the first failure and paste the whole
terminal output into an issue at
https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/issues
with the label platform-installer. Do not debug it yourself.

What a partial run may leave behind:
  $HOME/.local/bin/micromamba  (only if this script installed it)
  $HOME/micromamba             (root prefix, with an env named tavi)
  $HOME/TAVI
The uninstaller removes the env and the folder.

This installer will do the following:
  1. Install or reuse micromamba at:
     $HOME/.local/bin/micromamba
  2. Create or update the micromamba environment '$ENV_NAME' at:
     $MAMBA_ROOT_PREFIX
  3. Install or update TAVI at:
     $INSTALL_DIR
  4. Configure McStas/McStasScript paths for the installed environment.
  5. Build the lead-sample dispersion map (about 150 MB, a few minutes).
  6. Create run/update scripts inside the TAVI folder.

This installer will NOT run 'micromamba shell init' and will NOT modify any
shell startup file (.bashrc, .zshrc, etc).

If an existing '$ENV_NAME' environment is found, you will be asked whether to
recreate it or update it in place before any removal occurs.
============================================================================
EOF
    printf '%s' "Continue with TAVI installation? [y/N] "
    read -r reply || reply=""
    case "${reply:-}" in
        y|Y) ;;
        *)
            echo "Installation cancelled."
            exit 0
            ;;
    esac
    echo

    # --- Step 4: micromamba ---------------------------------------------------
    echo "[Step 1/6] Setting up micromamba..."
    if command -v micromamba >/dev/null 2>&1; then
        micromamba_exe=$(command -v micromamba)
        echo "[OK] Using micromamba already on PATH: $micromamba_exe"
    elif [ -x "$HOME/.local/bin/micromamba" ]; then
        micromamba_exe="$HOME/.local/bin/micromamba"
        echo "[OK] Using existing micromamba: $micromamba_exe"
    else
        local tmp_mamba download_url
        mkdir -p "$HOME/.local/bin"
        tmp_mamba=$(mktemp)
        download_url="https://github.com/mamba-org/micromamba-releases/releases/download/$MAMBA_VERSION/$mamba_asset"
        echo "[INFO] Downloading micromamba $MAMBA_VERSION ($mamba_asset)..."
        if [ "$downloader" = curl ]; then
            if ! curl -fL --retry 2 -o "$tmp_mamba" "$download_url"; then
                echo "[ERROR] Failed to download micromamba." >&2
                rm -f "$tmp_mamba"
                exit 1
            fi
        else
            if ! wget -O "$tmp_mamba" "$download_url"; then
                echo "[ERROR] Failed to download micromamba." >&2
                rm -f "$tmp_mamba"
                exit 1
            fi
        fi
        if ! verify_sha256 "$tmp_mamba" "$mamba_sha256"; then
            echo "[ERROR] Micromamba checksum verification failed." >&2
            echo "        Expected SHA256: $mamba_sha256" >&2
            rm -f "$tmp_mamba"
            exit 1
        fi
        echo "[OK] Micromamba checksum verified."
        chmod 0755 "$tmp_mamba"
        mv "$tmp_mamba" "$HOME/.local/bin/micromamba"
        micromamba_exe="$HOME/.local/bin/micromamba"
    fi

    export MAMBA_ROOT_PREFIX
    if ! "$micromamba_exe" --version >/dev/null; then
        echo "[ERROR] micromamba at $micromamba_exe failed to run." >&2
        exit 1
    fi
    echo "[OK] Micromamba ready."
    echo

    # --- Step 5: environment ---------------------------------------------------
    echo "[Step 2/6] Creating or updating environment '$ENV_NAME'..."
    conda_packages="python=$PYTHON_VERSION mcstas=$MCSTAS_VERSION mcstas-core=$MCSTAS_VERSION mcstas-data=$MCSTAS_VERSION mcstas-mcgui=$MCSTAS_VERSION mcstas-vis=$MCSTAS_VERSION numpy scipy matplotlib h5py pyyaml git"
    env_prefix="$MAMBA_ROOT_PREFIX/envs/$ENV_NAME"

    if [ -d "$env_prefix/conda-meta" ]; then
        echo "[INFO] Environment '$ENV_NAME' already exists."
        printf '%s' "Recreate from scratch (y) or update in place (N)? "
        read -r reply || reply=""
        case "${reply:-}" in
            y|Y)
                echo "[INFO] Removing existing '$ENV_NAME' environment..."
                if ! "$micromamba_exe" env remove -n "$ENV_NAME" -y; then
                    echo "[WARN] Environment removal reported an error; continuing." >&2
                fi
                echo "[INFO] Creating environment with packages: $conda_packages"
                "$micromamba_exe" create -n "$ENV_NAME" $conda_packages -c conda-forge -c nodefaults -y
                ;;
            *)
                echo "[INFO] Updating environment with packages: $conda_packages"
                "$micromamba_exe" install -n "$ENV_NAME" $conda_packages -c conda-forge -c nodefaults -y
                ;;
        esac
    elif [ -e "$env_prefix" ]; then
        echo "[WARN] A non-conda or incomplete folder already exists at:" >&2
        echo "       $env_prefix" >&2
        printf '%s' "Move this broken folder aside and create a fresh environment? [y/N] "
        read -r reply || reply=""
        case "${reply:-}" in
            y|Y)
                broken_backup="${env_prefix}_broken_$(date +%Y%m%d%H%M%S)"
                echo "[INFO] Moving broken environment folder to: $broken_backup"
                mv "$env_prefix" "$broken_backup"
                echo "[INFO] Creating environment with packages: $conda_packages"
                "$micromamba_exe" create -n "$ENV_NAME" $conda_packages -c conda-forge -c nodefaults -y
                ;;
            *)
                echo "[ERROR] Cannot create the environment while this folder exists." >&2
                echo "        Manually rename or delete: $env_prefix" >&2
                exit 1
                ;;
        esac
    else
        echo "[INFO] Creating environment with packages: $conda_packages"
        "$micromamba_exe" create -n "$ENV_NAME" $conda_packages -c conda-forge -c nodefaults -y
    fi

    echo "[INFO] Installing/upgrading pip packages..."
    if ! "$micromamba_exe" run -n "$ENV_NAME" python -m pip install --upgrade pip; then
        echo "[ERROR] Failed to upgrade pip." >&2
        exit 1
    fi
    if ! "$micromamba_exe" run -n "$ENV_NAME" python -m pip install --upgrade PySide6 mcstasscript; then
        echo "[ERROR] Pip package install failed." >&2
        exit 1
    fi
    echo "[OK] Python packages ready."
    echo

    env_prefix=$("$micromamba_exe" run -n "$ENV_NAME" python -c 'import sys; print(sys.prefix)')

    # --- Step 6: source ---------------------------------------------------------
    echo "[Step 3/6] Installing or updating TAVI source..."
    if [ -e "$INSTALL_DIR/.git" ]; then
        echo "[INFO] Existing TAVI Git repository found."
        echo "[INFO] Pinning checkout to release tag $TAVI_VERSION..."
        if ! (cd "$INSTALL_DIR" && "$micromamba_exe" run -n "$ENV_NAME" git fetch --tags origin); then
            echo "[ERROR] Failed to fetch tags from GitHub." >&2
            exit 1
        fi
        if ! (cd "$INSTALL_DIR" && "$micromamba_exe" run -n "$ENV_NAME" git checkout "$TAVI_VERSION"); then
            echo "[ERROR] Failed to check out release tag $TAVI_VERSION." >&2
            echo "        Confirm the tag exists on GitHub before running this installer." >&2
            exit 1
        fi
    elif [ -e "$INSTALL_DIR" ]; then
        backup_dir="${INSTALL_DIR}_backup_$(date +%Y%m%d%H%M%S)"
        echo "[WARN] $INSTALL_DIR exists but is not a Git repository." >&2
        echo "[INFO] Moving existing folder to: $backup_dir"
        mv "$INSTALL_DIR" "$backup_dir"
        if ! "$micromamba_exe" run -n "$ENV_NAME" git clone --branch "$TAVI_VERSION" --depth 1 --single-branch "$REPO_URL" "$INSTALL_DIR"; then
            echo "[ERROR] Failed to clone TAVI." >&2
            exit 1
        fi
    else
        if ! "$micromamba_exe" run -n "$ENV_NAME" git clone --branch "$TAVI_VERSION" --depth 1 --single-branch "$REPO_URL" "$INSTALL_DIR"; then
            echo "[ERROR] Failed to clone TAVI." >&2
            exit 1
        fi
    fi

    if [ ! -e "$INSTALL_DIR/TAVI_PySide6.py" ]; then
        echo "[ERROR] TAVI_PySide6.py not found after clone/update." >&2
        exit 1
    fi
    if [ ! -e "$INSTALL_DIR/tavi/mcstas_config.py" ]; then
        echo "[ERROR] tavi/mcstas_config.py not found after clone/update." >&2
        echo "        This release tag is incomplete or the file was not committed." >&2
        exit 1
    fi
    echo "[OK] TAVI source ready."
    echo

    # --- Step 7: McStas paths ---------------------------------------------------
    echo "[Step 4/6] Detecting McStas paths..."
    mcstas_resources="$env_prefix/share/mcstas/resources"
    mcrun="$env_prefix/bin/mcrun"

    if [ ! -d "$mcstas_resources" ]; then
        echo "[ERROR] McStas resources not found." >&2
        echo "        Tried: $mcstas_resources" >&2
        exit 1
    fi
    if [ ! -e "$mcrun" ]; then
        echo "[ERROR] mcrun not found in the expected environment directory." >&2
        echo "        Tried: $mcrun" >&2
        exit 1
    fi

    progress_bar=$(find "$mcstas_resources" -name "Progress_bar.comp" 2>/dev/null | head -n 1)
    if [ -z "$progress_bar" ]; then
        echo "[ERROR] Progress_bar.comp was not found under:" >&2
        echo "        $mcstas_resources" >&2
        echo "        McStas is installed, but this package layout/version lacks the component TAVI requests." >&2
        exit 1
    fi
    echo "[OK] McStas resources: $mcstas_resources"
    echo "[OK] mcrun            : $mcrun"

    tmp_cfg=$(mktemp)
    cat > "$tmp_cfg" <<PYEOF
import mcstasscript as ms
c = ms.Configurator()
c.set_mcrun_path("$env_prefix/bin")
c.set_mcstas_path("$mcstas_resources")
print("[TAVI] McStasScript configured")
PYEOF
    if ! "$micromamba_exe" run -n "$ENV_NAME" python "$tmp_cfg"; then
        rm -f "$tmp_cfg"
        echo "[ERROR] McStasScript configuration failed." >&2
        exit 1
    fi
    rm -f "$tmp_cfg"
    echo

    # --- Step 8: Pb dispersion map -----------------------------------------------
    echo "[Step 5/6] Building the lead-sample dispersion map..."
    pb_map=ok
    pb_map_file="$INSTALL_DIR/components/Pb_dft_phonons.dat"
    if [ -e "$pb_map_file" ]; then
        echo "[OK] components/Pb_dft_phonons.dat already present."
    else
        echo "[INFO] Building components/Pb_dft_phonons.dat: about 150 MB, a few minutes,"
        echo "       with no output until it finishes. Please wait."
        if ! (cd "$INSTALL_DIR" && "$micromamba_exe" run -n "$ENV_NAME" python "$INSTALL_DIR/tools/make_pb_assets.py"); then
            pb_map=missing
            rm -f "$pb_map_file"
            echo "[WARN] Building the lead-sample dispersion map failed." >&2
            echo "       TAVI still works. The \"Pb: Phonon DFT\" sample stays listed, but a run" >&2
            echo "       with it fails at asset load until the map exists. To retry, run:" >&2
            echo "           python tools/make_pb_assets.py" >&2
            echo "       inside: \"$micromamba_exe\" run -n $ENV_NAME" >&2
        else
            echo "[OK] Lead-sample dispersion map built."
        fi
    fi
    echo

    # --- Step 9: generated files --------------------------------------------------
    echo "[Step 6/6] Creating run/update scripts..."

    run_script="$INSTALL_DIR/run-tavi.sh"
    cat > "$run_script" <<EOF
#!/bin/bash
set -e
cd "$INSTALL_DIR"
export MCSTAS="$mcstas_resources"
export MCSTAS_COMPONENT_PATH="\$MCSTAS"
export MAMBA_ROOT_PREFIX="$MAMBA_ROOT_PREFIX"
if [ ! -d "\$MCSTAS" ]; then
    echo "McStas resource directory not found: \$MCSTAS" >&2
    exit 1
fi
exec "$micromamba_exe" run -n $ENV_NAME python TAVI_PySide6.py "\$@"
EOF
    chmod +x "$run_script"

    if [ "$os" = "Darwin" ]; then
        command_script="$INSTALL_DIR/run-tavi.command"
        cat > "$command_script" <<'EOF'
#!/bin/bash
# Finder runs .command files in Terminal.
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/run-tavi.sh"
EOF
        chmod +x "$command_script"
    fi

    update_script="$INSTALL_DIR/update-tavi.sh"
    cat > "$update_script" <<EOF
#!/bin/bash
set -e
echo "This installation is pinned to release tag $TAVI_VERSION."
echo "This script repairs/re-checks that exact tag. It does not pull main."
cd "$INSTALL_DIR"
echo "[INFO] Fetching tags from GitHub..."
"$micromamba_exe" run -n $ENV_NAME git fetch --tags origin
echo "[INFO] Checking out $TAVI_VERSION..."
"$micromamba_exe" run -n $ENV_NAME git checkout "$TAVI_VERSION"
echo "[INFO] Updating pip packages within the pinned installation environment..."
"$micromamba_exe" run -n $ENV_NAME python -m pip install --upgrade PySide6 mcstasscript
echo "[OK] Repair complete. Installed source remains pinned to $TAVI_VERSION."
EOF
    chmod +x "$update_script"

    cat > "$INSTALL_DIR/INSTALL_INFO.txt" <<EOF
TAVI_VERSION=$TAVI_VERSION
INSTALLER_VERSION=$INSTALLER_VERSION
PYTHON_VERSION=$PYTHON_VERSION
MCSTAS_VERSION=$MCSTAS_VERSION
MAMBA_VERSION=$MAMBA_VERSION
MICROMAMBA_EXE=$micromamba_exe
MAMBA_ROOT_PREFIX=$MAMBA_ROOT_PREFIX
ENV_NAME=$ENV_NAME
ENV_PREFIX=$env_prefix
REPO_URL=$REPO_URL
PB_MAP=$pb_map
PLATFORM=$os/$arch
EOF
    echo "[OK] Wrote install metadata to $INSTALL_DIR/INSTALL_INFO.txt"
    echo

    # --- Step 10: final block -----------------------------------------------------
    echo "============================================================================"
    echo "Installation complete."
    echo "Installed to: $INSTALL_DIR"
    echo "Environment : $ENV_NAME"
    echo "TAVI version: $TAVI_VERSION"
    echo "McStas      : $MCSTAS_VERSION"
    echo "============================================================================"
    if [ "$pb_map" = "missing" ]; then
        echo
        echo "[WARN] The lead-sample dispersion map was not built. The \"Pb: Phonon DFT\""
        echo "       sample will not run until you run:"
        echo "           python tools/make_pb_assets.py"
        echo "       inside: \"$micromamba_exe\" run -n $ENV_NAME"
    fi
    echo
    echo "Run:"
    echo "  bash \"$INSTALL_DIR/run-tavi.sh\""
    if [ "$os" = "Darwin" ]; then
        echo "  (or double-click run-tavi.command in the TAVI folder)"
    fi
}

# Allow sourcing this file (e.g. to test verify_sha256 directly) without
# running the installer itself.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
