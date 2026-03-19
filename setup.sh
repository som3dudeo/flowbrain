#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  n8n Flow Finder — One-Click Setup Script
#  Run: bash setup.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo ""
echo -e "${BOLD}⚡  n8n Flow Finder — Setup${NC}"
echo "────────────────────────────────────────"
echo ""

# ── 1. Check Python version ───────────────────────────────────────────────────
echo -e "${CYAN}[1/5]${NC} Checking Python..."
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}✗ Python 3 not found.${NC}"
    echo "  Install it from https://www.python.org/downloads/ and re-run this script."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "  ${GREEN}✓${NC} Python $PYTHON_VERSION found"

if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
    echo -e "  ${GREEN}✓${NC} Version is 3.10+ (required)"
else
    echo -e "${RED}✗ Python 3.10+ is required. You have $PYTHON_VERSION${NC}"
    echo "  Download a newer version from https://www.python.org/downloads/"
    exit 1
fi

# ── 2. Create virtual environment ─────────────────────────────────────────────
echo ""
echo -e "${CYAN}[2/5]${NC} Setting up virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "  ${GREEN}✓${NC} Created virtual environment in ./venv/"
else
    echo -e "  ${GREEN}✓${NC} Virtual environment already exists"
fi

source venv/bin/activate

# ── 3. Install dependencies ───────────────────────────────────────────────────
echo ""
echo -e "${CYAN}[3/5]${NC} Installing Python packages..."
echo "  (This may take 2-3 minutes on first run)"
echo ""
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo -e "  ${GREEN}✓${NC} All packages installed"

# ── 4. Create .env file ───────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}[4/5]${NC} Setting up configuration..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo -e "  ${GREEN}✓${NC} Created .env from template"
    echo -e "  ${YELLOW}→${NC}  Edit .env to add your n8n webhook URLs (optional for now)"
else
    echo -e "  ${GREEN}✓${NC} .env already exists"
fi

mkdir -p data/workflows

# ── 5. Done ───────────────────────────────────────────────────────────────────
echo ""
echo "────────────────────────────────────────"
echo -e "${GREEN}${BOLD}✅ Setup complete!${NC}"
echo ""
echo -e "${BOLD}Next steps:${NC}"
echo ""
echo -e "  ${CYAN}Step 1${NC} — Download n8n workflows (takes ~5 minutes for 2,000 workflows):"
echo "           python harvester.py"
echo ""
echo -e "  ${CYAN}Step 2${NC} — Build the semantic index (takes ~3 minutes):"
echo "           python indexer.py"
echo ""
echo -e "  ${CYAN}Step 3${NC} — Start the web server:"
echo "           python server.py"
echo ""
echo -e "  ${CYAN}Step 4${NC} — Open in your browser:"
echo "           http://localhost:8000"
echo ""
echo -e "  ${YELLOW}Tip:${NC} You can do Steps 1-3 all at once with:"
echo "         python harvester.py && python indexer.py && python server.py"
echo ""
echo "────────────────────────────────────────"
echo ""
