#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  FlowBrain — Remote one-command installer (clone + bootstrap)
#
#  Usage (from anywhere):
#    curl -fsSL https://raw.githubusercontent.com/som3dudeo/flowbrain/main/install.sh | bash
#
#  What it does:
#    1. Checks prerequisites (Python 3.10+, git)
#    2. Clones (or updates) the repo to ~/Documents/flowbrain
#    3. Delegates to bootstrap.sh for venv, deps, index, and doctor
#
#  This is the "from zero" path.  If you already have the repo cloned, run
#  `bash bootstrap.sh` directly instead.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

REPO="https://github.com/som3dudeo/flowbrain.git"
INSTALL_DIR="$HOME/Documents/flowbrain"

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo -e "${BOLD}FlowBrain — One-Command Installer${NC}"
echo "────────────────────────────────────────────────────"

# ── Prerequisites ─────────────────────────────────────────────────────────────
check_cmd() {
    if ! command -v "$1" &>/dev/null; then
        echo -e "  ${RED}✗${NC}  Required: $1 is not installed."
        echo "     $2"
        exit 1
    fi
}

check_cmd git       "Install git from https://git-scm.com"

# Find a Python 3.10+ interpreter
PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "  ${RED}✗${NC}  Python 3.10+ is required but not found."
    echo "     Download from https://www.python.org/downloads/"
    exit 1
fi

PY_VERSION=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
echo -e "  ${GREEN}✓${NC}  Python ${PY_VERSION}"
echo -e "  ${GREEN}✓${NC}  git $(git --version | awk '{print $3}')"

# ── Clone or update ───────────────────────────────────────────────────────────
echo ""
if [ -d "$INSTALL_DIR/.git" ]; then
    echo -e "  ${CYAN}Updating${NC} existing installation at $INSTALL_DIR..."
    cd "$INSTALL_DIR" && git pull --ff-only
else
    echo -e "  ${CYAN}Cloning${NC} FlowBrain to $INSTALL_DIR..."
    git clone "$REPO" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# ── Delegate to bootstrap.sh ─────────────────────────────────────────────────
if [ -f "bootstrap.sh" ]; then
    exec bash bootstrap.sh
else
    echo -e "  ${RED}✗${NC}  bootstrap.sh not found in repo. Something went wrong with the clone."
    exit 1
fi
