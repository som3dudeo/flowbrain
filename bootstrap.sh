#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  FlowBrain — Single-command bootstrap (post-clone)
#
#  Usage:
#    git clone https://github.com/som3dudeo/flowbrain.git
#    cd flowbrain && bash bootstrap.sh
#
#  What it does:
#    1. Checks Python 3.10+
#    2. Creates (or reuses) a virtual environment
#    3. Installs all Python dependencies
#    4. Creates .env from .env.example if needed
#    5. Runs `flowbrain install` (downloads workflows, builds index, runs doctor)
#    6. Prints exact next steps
#
#  This script is idempotent — safe to rerun at any time.
#  Exits nonzero on any real failure.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
DIM='\033[2m'
NC='\033[0m'

echo ""
echo -e "${BOLD}FlowBrain — Bootstrap${NC}"
echo "────────────────────────────────────────────────────"

# ── 1. Python version check ──────────────────────────────────────────────────
echo ""
echo -e "${CYAN}[1/5]${NC} ${BOLD}Checking Python...${NC}"

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
echo -e "  ${GREEN}✓${NC}  Python ${PY_VERSION} (${PYTHON})"

# ── 2. Virtual environment ───────────────────────────────────────────────────
echo ""
echo -e "${CYAN}[2/5]${NC} ${BOLD}Setting up virtual environment...${NC}"

if [ ! -d "venv" ]; then
    "$PYTHON" -m venv venv
    echo -e "  ${GREEN}✓${NC}  Created venv/"
else
    echo -e "  ${GREEN}✓${NC}  venv/ already exists"
fi

# shellcheck disable=SC1091
source venv/bin/activate

# ── 3. Install dependencies ──────────────────────────────────────────────────
echo ""
echo -e "${CYAN}[3/5]${NC} ${BOLD}Installing dependencies...${NC}"
echo -e "  ${DIM}(First run downloads ML model — may take 2-5 minutes)${NC}"

pip install --upgrade pip -q 2>/dev/null
pip install -q -r requirements.txt
echo -e "  ${GREEN}✓${NC}  All packages installed"

# ── 4. Environment config ────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}[4/5]${NC} ${BOLD}Checking configuration...${NC}"

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp .env.example .env
    echo -e "  ${GREEN}✓${NC}  Created .env from .env.example"
    echo -e "  ${YELLOW}⚠${NC}  Edit .env to set N8N_DEFAULT_WEBHOOK for live execution"
elif [ -f ".env" ]; then
    echo -e "  ${GREEN}✓${NC}  .env already exists"
else
    echo -e "  ${YELLOW}⚠${NC}  No .env.example found — using defaults"
fi

# ── 5. Run flowbrain install ─────────────────────────────────────────────────
echo ""
echo -e "${CYAN}[5/5]${NC} ${BOLD}Running FlowBrain installer...${NC}"
echo ""

python -m flowbrain install

# ── Done ─────────────────────────────────────────────────────────────────────
echo "────────────────────────────────────────────────────"
echo -e "${GREEN}${BOLD}FlowBrain is ready!${NC}"
echo ""
echo -e "  Start the server:"
echo -e "    ${CYAN}source venv/bin/activate && python -m flowbrain start${NC}"
echo ""
echo -e "  Quick test:"
echo -e "    ${CYAN}source venv/bin/activate && python -m flowbrain search \"send slack message\"${NC}"
echo ""
echo -e "  ${DIM}Server runs at http://127.0.0.1:8001${NC}"
echo "────────────────────────────────────────────────────"
echo ""
