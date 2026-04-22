#!/usr/bin/env bash
# =============================================================================
# setup_miner_test.sh — One-shot Sparket miner testnet setup
#
# What this script does:
#   1. Activates the bittensor-env and uv venv
#   2. Installs uv dependencies
#   3. Creates the sparket-miner hotkey under itsai-testnet-cold0 (if missing)
#   4. Opens axon port 8094 in UFW
#   5. Starts the isolated test Postgres container (port 5435)
#   6. Runs database migrations
#   7. Prompts you to pass the mining interview
#   8. Prints registration instructions (requires testTAO)
#
# Usage:
#   bash scripts/setup_miner_test.sh
# =============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COLDKEY_NAME="itsai-testnet-cold0"
HOTKEY_NAME="sparket-miner"
AXON_PORT=8094
DB_PORT=5435
DB_NAME="sparket_miner_test"
DB_USER="sparket"
DB_PASSWORD="sparket"
DB_CONTAINER="pg-sparket-miner-test"
DB_VOLUME="pg_sparket_miner_test_data"
BITTENSOR_VENV="$HOME/bittensor-env"
UV_VENV="$PROJECT_ROOT/.venv"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

step() { echo -e "\n${GREEN}[STEP]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
info() { echo -e "       $*"; }

# ── Step 0: sanity checks ────────────────────────────────────────────────────
step "Checking prerequisites"
cd "$PROJECT_ROOT"

# Activate bittensor-env for btcli
if [[ -f "$BITTENSOR_VENV/bin/activate" ]]; then
  # shellcheck disable=SC1090
  source "$BITTENSOR_VENV/bin/activate"
  info "bittensor-env activated: $(which btcli)"
else
  warn "bittensor-env not found at $BITTENSOR_VENV — btcli may not be available"
fi

command -v docker >/dev/null 2>&1 || { echo -e "${RED}[ERROR]${NC} docker is required. Install with: sudo apt install docker.io"; exit 1; }
command -v uv     >/dev/null 2>&1 || { echo -e "${RED}[ERROR]${NC} uv is required. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }

# ── Step 1: Install Python dependencies ─────────────────────────────────────
step "Installing Python dependencies via uv"
uv python install 3.10
uv sync --dev
info "venv created at $UV_VENV"

# ── Step 2: Create sparket-miner hotkey ─────────────────────────────────────
step "Creating hotkey '$HOTKEY_NAME' under coldkey '$COLDKEY_NAME'"
if btcli wallet overview --wallet.name "$COLDKEY_NAME" --wallet.hotkey "$HOTKEY_NAME" \
     --subtensor.network test 2>&1 | grep -q "$HOTKEY_NAME"; then
  warn "Hotkey '$HOTKEY_NAME' already exists — skipping creation"
else
  btcli wallet new_hotkey \
    --wallet.name "$COLDKEY_NAME" \
    --wallet.hotkey "$HOTKEY_NAME" \
    --no_prompt
  info "Hotkey created."
fi

# ── Step 3: Open axon port ───────────────────────────────────────────────────
step "Opening axon port $AXON_PORT in UFW"
if command -v ufw >/dev/null 2>&1; then
  sudo ufw allow "${AXON_PORT}/tcp" || warn "UFW rule may already exist — continuing"
  sudo ufw --force enable
  sudo ufw status | grep "$AXON_PORT"
else
  warn "UFW not found — open port $AXON_PORT manually in your cloud security group"
fi

# ── Step 4: Start test Postgres container ───────────────────────────────────
step "Starting isolated test Postgres on port $DB_PORT"
if docker ps --format '{{.Names}}' | grep -q "^${DB_CONTAINER}$"; then
  warn "Container '$DB_CONTAINER' already running — skipping"
else
  # Remove stopped container if it exists
  docker rm -f "$DB_CONTAINER" 2>/dev/null || true
  docker run -d \
    --name "$DB_CONTAINER" \
    -e POSTGRES_USER="$DB_USER" \
    -e POSTGRES_PASSWORD="$DB_PASSWORD" \
    -e POSTGRES_DB="$DB_NAME" \
    -p "${DB_PORT}:5432" \
    -v "${DB_VOLUME}:/var/lib/postgresql/data" \
    --restart unless-stopped \
    postgres:18
  info "Waiting for Postgres to be ready..."
  sleep 5
  # Wait up to 30s for Postgres to accept connections
  for i in $(seq 1 30); do
    if docker exec "$DB_CONTAINER" pg_isready -U "$DB_USER" >/dev/null 2>&1; then
      info "Postgres is ready (took ${i}s)"
      break
    fi
    sleep 1
  done
fi

# ── Step 5: Run database migrations ─────────────────────────────────────────
step "Running Alembic migrations"
export DATABASE_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@127.0.0.1:${DB_PORT}/${DB_NAME}"
export SPARKET_ROLE=miner
export SPARKET_MINER_CONFIG_FILE="$PROJECT_ROOT/sparket/config/miner.test.yaml"

"$UV_VENV/bin/sparket-alembic" upgrade head
info "Migrations complete."

# ── Step 6: Mining interview ─────────────────────────────────────────────────
step "Running the Sparket mining interview (required to unlock base miner)"
echo ""
echo -e "${YELLOW}Read docs/miner.md carefully before proceeding.${NC}"
echo "Press Enter to launch the interview, or Ctrl+C to skip and run it later:"
read -r
"$UV_VENV/bin/python" -m sparket.tools.mining_interview

# ── Step 7: Print registration instructions ──────────────────────────────────
step "Setup complete — next steps"
echo ""
echo "  1. Get testTAO from the Bittensor faucet:"
echo "       https://discord.com/channels/799672011265015819 (tap the #bittensor-faucet channel)"
echo ""
echo "  2. Confirm the Sparket testnet netuid at:"
echo "       https://x.taostats.io/?network=test"
echo "     Then update SPARKET_CHAIN__NETUID in .env.test"
echo ""
echo "  3. Register your hotkey on the testnet:"
echo ""
echo "     source $BITTENSOR_VENV/bin/activate"
echo "     btcli subnet register \\"
echo "       --wallet.name $COLDKEY_NAME \\"
echo "       --wallet.hotkey $HOTKEY_NAME \\"
echo "       --netuid <TESTNET_NETUID> \\"
echo "       --subtensor.network test"
echo ""
echo "  4. Verify port $AXON_PORT is reachable (run from another machine):"
echo "       nc -vz <your-vps-public-ip> $AXON_PORT"
echo ""
echo "  5. Start the miner:"
echo "       cd $PROJECT_ROOT"
echo "       set -a && source .env.test && set +a"
echo "       $UV_VENV/bin/python sparket/entrypoints/miner.py"
echo ""
echo "     Or with PM2:"
echo "       pm2 start ecosystem.miner.config.js"
echo "       pm2 logs miner-local"
echo ""
echo "  6. Verify the 5 milestones in the logs (see docs/miner.md §First Run Verification)"
echo ""
echo -e "${GREEN}Done.${NC}"
