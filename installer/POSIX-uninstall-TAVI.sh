#!/bin/bash
#
# TAVI POSIX uninstaller - release-pinned v1.3.0
#
# PROVISIONAL: written 2026-09-14 and never executed on macOS or Linux by the
# maintainer. This mirrors installer/WINDOWS-uninstall-TAVI.bat but has no
# platform coverage of its own yet.
#
# If it fails, stop at the first failure and paste the whole terminal output
# into an issue at
# https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/issues
# with the label platform-installer. Do not debug it yourself.
#
# Removes only the user TAVI install and its micromamba environment. It never
# removes micromamba itself, the micromamba root prefix, or any other
# environment.

set -euo pipefail

INSTALL_DIR="$HOME/TAVI"

main() {
    local micromamba_exe mamba_root_prefix env_name key value reply

    micromamba_exe=""
    mamba_root_prefix=""
    env_name=""

    if [ -f "$INSTALL_DIR/INSTALL_INFO.txt" ]; then
        while IFS='=' read -r key value; do
            case "$key" in
                MICROMAMBA_EXE) micromamba_exe="$value" ;;
                MAMBA_ROOT_PREFIX) mamba_root_prefix="$value" ;;
                ENV_NAME) env_name="$value" ;;
                *) ;;
            esac
        done < "$INSTALL_DIR/INSTALL_INFO.txt"
    fi

    if [ -z "${micromamba_exe:-}" ]; then
        if command -v micromamba >/dev/null 2>&1; then
            micromamba_exe=$(command -v micromamba)
        else
            micromamba_exe="$HOME/.local/bin/micromamba"
        fi
    fi
    if [ -z "${mamba_root_prefix:-}" ]; then
        mamba_root_prefix="$HOME/micromamba"
    fi
    if [ -z "${env_name:-}" ]; then
        env_name="tavi"
    fi

    cat <<EOF
============================================================================
                    TAVI POSIX Uninstaller
============================================================================
PROVISIONAL: written 2026-09-14 and never executed on macOS or Linux by the
maintainer. If it fails, stop at the first failure and paste the whole
terminal output into an issue at
https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/issues
with the label platform-installer. Do not debug it yourself.

This will remove:
  Environment : $env_name (under $mamba_root_prefix)
  TAVI folder : $INSTALL_DIR

This will NOT remove:
  micromamba itself
  the micromamba root prefix ($mamba_root_prefix)
  any other environment
  Xcode command line tools
============================================================================
EOF
    printf '%s' "Proceed? [y/N] "
    read -r reply || reply=""
    case "${reply:-}" in
        y|Y) ;;
        *)
            echo "Uninstall cancelled."
            exit 0
            ;;
    esac
    echo

    echo "[Step 1/2] Removing environment '$env_name'..."
    if [ -x "$micromamba_exe" ] || command -v "$micromamba_exe" >/dev/null 2>&1; then
        export MAMBA_ROOT_PREFIX="$mamba_root_prefix"
        if ! "$micromamba_exe" env remove -n "$env_name" -y; then
            echo "[WARN] Environment removal reported an error or the env was already absent." >&2
        else
            echo "[OK] Removed environment '$env_name'."
        fi
    else
        echo "[WARN] micromamba not found at $micromamba_exe; skipping environment removal." >&2
    fi
    echo

    echo "[Step 2/2] Removing TAVI directory..."
    if [ -z "$INSTALL_DIR" ] || [ "$INSTALL_DIR" = "/" ]; then
        echo "[ERROR] Refusing to remove an unsafe INSTALL_DIR value." >&2
        exit 1
    fi
    if [ ! -e "$INSTALL_DIR" ]; then
        echo "[INFO] TAVI directory not found."
    elif [ -f "$INSTALL_DIR/TAVI_PySide6.py" ]; then
        rm -rf "$INSTALL_DIR"
        echo "[OK] Removed $INSTALL_DIR."
    else
        echo "[ERROR] $INSTALL_DIR does not contain TAVI_PySide6.py; refusing to delete it." >&2
        echo "        This protects against removing the wrong folder. Remove it manually" >&2
        echo "        if you are sure it is the right one." >&2
        exit 1
    fi
    echo
    echo "[OK] Uninstall complete."
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
