#!/usr/bin/env bash
# ⚡ n8n Flow Finder — OpenClaw Automation Skill Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/abdullahalbukhari/n8n-flow-finder/main/install.sh | bash

set -e

REPO="https://github.com/abdullahalbukhari/n8n-flow-finder.git"
INSTALL_DIR="$HOME/Documents/n8n-flow-finder"
OPENCLAW_SKILLS_DIR="/opt/homebrew/lib/node_modules/openclaw/skills/n8n-flows"

echo ""
echo "⚡ n8n Flow Finder — OpenClaw Automation Skill"
echo "================================================"
echo ""

# ── Check requirements ──────────────────────────────────────────────────────
check_cmd() {
    if ! command -v "$1" &>/dev/null; then
        echo "❌ Required: $1 is not installed."
        echo "   $2"
        exit 1
    fi
}

check_cmd python3   "Install Python 3.10+ from https://python.org"
check_cmd git       "Install git from https://git-scm.com"
check_cmd pip3      "Install pip: python3 -m ensurepip"

PYTHON_VERSION=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PYTHON_VERSION" -lt 10 ]; then
    echo "❌ Python 3.10+ required (found 3.$PYTHON_VERSION)"
    exit 1
fi

echo "✓ Python $(python3 --version)"
echo "✓ git $(git --version | awk '{print $3}')"
echo ""

# ── Clone or update ──────────────────────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "📦 Updating existing installation at $INSTALL_DIR..."
    cd "$INSTALL_DIR" && git pull --ff-only
else
    echo "📦 Cloning to $INSTALL_DIR..."
    git clone "$REPO" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# ── Virtual environment ──────────────────────────────────────────────────────
if [ ! -d "venv" ]; then
    echo "🐍 Creating Python virtual environment..."
    python3 -m venv venv
fi

echo "📚 Installing Python dependencies (this may take a few minutes)..."
source venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "✓ Dependencies installed"
echo ""

# ── Install OpenClaw skill ────────────────────────────────────────────────────
if command -v openclaw &>/dev/null; then
    echo "🦞 Installing n8n-flows skill into OpenClaw..."

    # Try the standard bundled skills location first
    POSSIBLE_DIRS=(
        "/opt/homebrew/lib/node_modules/openclaw/skills/n8n-flows"
        "/usr/local/lib/node_modules/openclaw/skills/n8n-flows"
        "$(npm root -g 2>/dev/null)/openclaw/skills/n8n-flows"
    )

    SKILL_INSTALLED=false
    for dir in "${POSSIBLE_DIRS[@]}"; do
        parent=$(dirname "$dir")
        if [ -d "$parent" ]; then
            mkdir -p "$dir"
            cp "$INSTALL_DIR/SKILL.md" "$dir/SKILL.md"
            SKILL_INSTALLED=true
            echo "✓ Skill installed at $dir"
            break
        fi
    done

    if [ "$SKILL_INSTALLED" = false ]; then
        echo "⚠️  Could not find OpenClaw skills directory."
        echo "   Manual install: copy SKILL.md to your OpenClaw skills folder."
    fi

    # Verify
    if openclaw skills list 2>/dev/null | grep -q "n8n-flows"; then
        echo "✓ n8n-flows skill is ready in OpenClaw"
    fi
else
    echo "ℹ️  OpenClaw not found — skipping skill registration."
    echo "   Install OpenClaw: https://openclaw.ai"
fi

echo ""

# ── Create .env if missing ────────────────────────────────────────────────────
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp .env.example .env
    echo "📝 Created .env from .env.example (edit to add n8n webhook URLs)"
fi

# ── Start the server ──────────────────────────────────────────────────────────
echo "🚀 Starting n8n Flow Finder server..."
echo "   (Downloading and indexing workflows in background — may take 2-3 min)"
echo ""

# Kill any existing instance on port 8000
lsof -ti:8000 | xargs kill -9 2>/dev/null || true

nohup bash -c "cd '$INSTALL_DIR' && source venv/bin/activate && python3 run.py --serve 2>&1" \
    > "$INSTALL_DIR/server.log" 2>&1 &

SERVER_PID=$!
echo "   Server PID: $SERVER_PID (log: $INSTALL_DIR/server.log)"
echo ""

# Wait for server to be ready
echo -n "   Waiting for server"
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/status &>/dev/null; then
        echo ""
        echo "✓ Server is up at http://localhost:8000"
        break
    fi
    echo -n "."
    sleep 2
done

echo ""

# ── Final check ──────────────────────────────────────────────────────────────
STATUS=$(curl -sf http://localhost:8000/status 2>/dev/null || echo '{}')
INDEXED=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('workflows_indexed', 0))" 2>/dev/null || echo "0")

echo "================================================"
echo "✅ Installation complete!"
echo ""
echo "   Workflows indexed: $INDEXED"
echo "   Server:           http://localhost:8000"
echo "   Chat UI:          http://localhost:8000"
echo ""

if command -v openclaw &>/dev/null; then
    echo "   OpenClaw skill:   ⚡ n8n-flows (✓ ready)"
    echo ""
    echo "   👉 Start a conversation with OpenClaw and say:"
    echo "      'Send an email to me@example.com saying hello'"
    echo "      'Post to Slack #general that the build is green'"
    echo "      'Create a Notion page for today's standup'"
fi

echo ""
echo "   📖 Next step: connect n8n for live execution"
echo "      1. Import n8n_dispatcher.json into your n8n instance"
echo "      2. Add N8N_DEFAULT_WEBHOOK=<url> to $INSTALL_DIR/.env"
echo "      3. Restart: cd $INSTALL_DIR && source venv/bin/activate && python3 run.py --serve"
echo ""
