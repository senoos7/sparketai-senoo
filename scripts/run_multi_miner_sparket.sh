#!/bin/bash
# ============================================================
# run_multi_miner_sparket.sh — manage multiple Sparket miners
#
# Each miner entry:  "WALLET  HOTKEY  PORT  PM2_NAME  API_PORT  LEAGUES  ELO_K"
#   WALLET     — bittensor coldkey wallet name
#   HOTKEY     — hotkey name (must be registered on netuid 57)
#   PORT       — unique axon port per miner (open in UFW)
#   PM2_NAME   — unique pm2 process name
#   API_PORT   — unique control API port per miner
#   LEAGUES    — comma-separated league codes (NO SPACES)
#   ELO_K      — Elo K-factor for this miner (differentiate models; use "-" for 32)
#
# LEAGUE SPLITTING STRATEGY (avoids Sybil/Uniqueness penalty):
#   Every group anchors on at least one US sport (ESPN-supported for outcomes).
#   Group A (US core + EPL):         nfl,nba,mlb,epl
#   Group B (US winter + S.Europe):  nhl,nba,la_liga,serie_a
#   Group C (US college + soccer):   ncaaf,ncaab,mls,bundesliga
#
# Prerequisite per new miner:
#   1. btcli wallet new_hotkey --wallet.name <wallet> --wallet.hotkey <hotkey>
#   2. btcli subnets register --netuid 57 --wallet.name <wallet> --wallet.hotkey <hotkey>
#   3. sudo ufw allow <PORT>/tcp
#
# Usage:
#   ./scripts/run_multi_miner_sparket.sh start
#   ./scripts/run_multi_miner_sparket.sh stop
#   ./scripts/run_multi_miner_sparket.sh restart
#   ./scripts/run_multi_miner_sparket.sh status
#   ./scripts/run_multi_miner_sparket.sh logs <pm2_name>
#   ./scripts/run_multi_miner_sparket.sh list
#   ./scripts/run_multi_miner_sparket.sh register   # check/show registration steps
# ============================================================

set -e

# ----------------------------------------------------------------
# Shared defaults
# ----------------------------------------------------------------
NETWORK="finney"
NETUID="57"
EXTERNAL_IP="${SPARKET_AXON__EXTERNAL_IP:-$(curl -s ifconfig.me 2>/dev/null || echo '0.0.0.0')}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# Prefer the project venv Python (has sparket installed); fall back to python3
PYTHON="${PYTHON:-${REPO_DIR}/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then PYTHON="$(which python3)"; fi
LOG_DIR="sparket/logs/pm2-mainnet"

# ----------------------------------------------------------------
# Miner definitions
# Format: "WALLET  HOTKEY  PORT  PM2_NAME  API_PORT  LEAGUES  ELO_K"
#
# UNIQUENESS STRATEGY — zero league overlap across all 5 miners.
# Each league appears in exactly ONE miner. With Uniqueness exponent=1.5
# this is the single biggest lever for increasing incentive.
#
#   Miner-01  nfl,epl              K=32  (American football + Premier League)
#   Miner-02  nba,la_liga          K=16  (Basketball + La Liga — conservative)
#   Miner-03  ncaaf,ncaab,bundesliga K=56 (College + Bundesliga — aggressive)
#   Miner-04  mlb,serie_a          K=24  (Baseball + Serie A)
#   Miner-05  nhl,mls              K=40  (Ice hockey + MLS)
#
# Prerequisites for new hotkeys (miner-04, miner-05):
#   btcli wallet new_hotkey --wallet.name darnsin01 --wallet.hotkey sparket-miner-04232
#   btcli wallet new_hotkey --wallet.name darnsin01 --wallet.hotkey sparket-miner-04233
#   btcli subnets register --netuid 57 --wallet.name darnsin01 --wallet.hotkey sparket-miner-04232
#   btcli subnets register --netuid 57 --wallet.name darnsin01 --wallet.hotkey sparket-miner-04233
#   sudo ufw allow 8097/tcp && sudo ufw allow 8098/tcp
# ----------------------------------------------------------------
MINERS=(
  # WALLET    HOTKEY                PORT  PM2_NAME         API_PORT  LEAGUES                  ELO_K
  #
  # Soccer league codes — validator uses SHORT codes (not long names):
  #   La Liga → "esp"   Serie A → "ita"   Bundesliga → "ger"   EPL → "epl"
  # EventSelector auto-aliases long names but short codes are used here directly.
  #
  # UOL: both current top-2 miners (p99-100 Marginal) submit exclusively to "uol"
  # — an obscure league with almost no other miners. Include in thin-market miners.
  #
  # Miner-01: nfl + epl + frl1  (strict edge filter, rank #3, longest Elo history)
  "darnsin01  sparket-miner-04220   8094  sparket-miner-01  9094     nfl,epl,frl1             32"
  # Miner-02: nba + esp  (La Liga = less contested than EPL; low K → conservative Elo)
  "darnsin00  sparket-miner-04230   8095  sparket-miner-02  9095     nba,esp                  16"
  # Miner-03: college + ger + uol  (thin/niche focus → high Marginal; aggressive K)
  "darnsin01  sparket-miner-04231   8096  sparket-miner-03  9096     ncaaf,ncaab,ger,uol      56"
  # Miner-04: mlb + ita  (baseball + Serie A; moderate K)
  "darnsin00  sparket-miner-04240   8097  sparket-miner-04  9097     mlb,ita                  24"
  # Miner-05: nhl + mls + uol  (thin ice/soccer markets; medium K)
  "darnsin00  sparket-miner-04241   8098  sparket-miner-05  9098     nhl,mls,uol              40"
  # Miner-06: nfl + nba  (popular leagues w/ very aggressive K=64 → diverges from miner-01 K=32 and miner-02 K=16)
  "darnsin00  sparket-miner-04242   8099  sparket-miner-06  9099     nfl,nba                  64"
)

# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------
require_pm2() {
  if ! command -v pm2 &>/dev/null; then
    echo "Error: pm2 is not installed. Run: npm install -g pm2"
    exit 1
  fi
}

require_btcli() {
  if ! command -v btcli &>/dev/null; then
    echo "Error: btcli is not installed. Activate bittensor venv first."
    exit 1
  fi
}

# Parse entry: sets _WALLET _HOTKEY _PORT _PM2_NAME _API_PORT _LEAGUES _ELO_K
parse_entry() {
  _WALLET=""; _HOTKEY=""; _PORT=""; _PM2_NAME=""; _API_PORT=""; _LEAGUES=""; _ELO_K=""
  read -r _WALLET _HOTKEY _PORT _PM2_NAME _API_PORT _LEAGUES _ELO_K <<< "$1" || true
  if [[ -z "$_ELO_K" || "$_ELO_K" == "-" ]]; then _ELO_K="32"; fi
}

# Env file path for a miner
env_file_for() { echo "${REPO_DIR}/.env.${1}"; }

# YAML config path for a miner
yaml_file_for() { echo "${REPO_DIR}/sparket/config/${1}.yaml"; }

# Wrapper script path for a miner (sources env then exec python)
wrapper_for() { echo "${REPO_DIR}/scripts/.run_${1}.sh"; }

# SQLite DB filename for a miner (unique per miner)
db_file_for() { echo "${1}.db"; }

# ----------------------------------------------------------------
# Generate per-miner wrapper script (sources .env then runs Python)
# Needed because older PM2 versions don't support --env-file.
# ----------------------------------------------------------------
generate_wrapper() {
  local pm2_name="$1"
  local env_path; env_path="$(env_file_for "$pm2_name")"
  local wrapper; wrapper="$(wrapper_for "$pm2_name")"
  cat > "$wrapper" << WRAPPER
#!/bin/bash
set -a
# shellcheck source=/dev/null
source "${env_path}"
set +a
export PYTHONPATH="${REPO_DIR}\${PYTHONPATH:+:\$PYTHONPATH}"
exec "${PYTHON}" "${REPO_DIR}/sparket/entrypoints/miner.py"
WRAPPER
  chmod +x "$wrapper"
}

# ----------------------------------------------------------------
# Generate per-miner .env file
# ----------------------------------------------------------------
generate_env() {
  local pm2_name="$1"
  local wallet="$2"
  local hotkey="$3"
  local port="$4"
  local api_port="$5"
  local leagues="$6"
  local elo_k="$7"
  local env_path
  env_path="$(env_file_for "$pm2_name")"
  local yaml_path="sparket/config/${pm2_name}.yaml"
  local db_file
  db_file="$(db_file_for "$pm2_name")"

  # Derive a unique model seed from the port number so each miner's
  # LightGBM produces different decision-tree splits → higher Uniqueness.
  local model_seed=$(( port * 7 + elo_k ))

  cat > "$env_path" << EOF
# Auto-generated by run_multi_miner_sparket.sh — DO NOT EDIT MANUALLY
# Miner: ${pm2_name}

SPARKET_ROLE=miner
SPARKET_SUBTENSOR__NETWORK=${NETWORK}
SPARKET_CHAIN__NETUID=${NETUID}

SPARKET_MINER_CONFIG_FILE=${yaml_path}
SPARKET_CONFIG_FILE=${yaml_path}

SPARKET_WALLET__NAME=${wallet}
SPARKET_WALLET__HOTKEY=${hotkey}

SPARKET_AXON__HOST=0.0.0.0
SPARKET_AXON__PORT=${port}
SPARKET_AXON__EXTERNAL_IP=${EXTERNAL_IP}
SPARKET_AXON__EXTERNAL_PORT=${port}

SPARKET_BASE_MINER__ENABLED=false

SPARKET_DATABASE__HOST=127.0.0.1
SPARKET_DATABASE__PORT=5432
SPARKET_DATABASE__USER=sparket
SPARKET_DATABASE__PASSWORD=${SPARKET_DATABASE__PASSWORD:-Password123!@#}
SPARKET_DATABASE__NAME=sparket_miner
SPARKET_DATABASE__FILENAME=${db_file}

SPARKET_MINER_API_ENABLED=true
SPARKET_MINER_API_PORT=${api_port}

COMPETITIVE_LEAGUES=${leagues}
COMPETITIVE_ODDS_INTERVAL=900
COMPETITIVE_OUTCOME_INTERVAL=300
COMPETITIVE_BATCH_SIZE=75
COMPETITIVE_MIN_HOURS_BEFORE=0
COMPETITIVE_SENTINEL_THRESHOLD=0.98
COMPETITIVE_ELO_K=${elo_k}
COMPETITIVE_MODEL_SEED=${model_seed}

# Submission quality filters (drives Edge + Marginal scores)
# Rank #0 analysis: p13 submissions, p90 Marginal, p80 Edge → selectivity beats volume.
# Strategy: submit less but only when model strongly disagrees with market.
#   miner-01: strictest (established, recovering Brier — keep conservative)
#   miner-06: strict (new, covers contested nfl+nba leagues — needs high edge to compete)
#   miner-03/05: medium (thin markets = fewer competitors = lower edge needed)
#   miner-02/04: standard
$(case "${pm2_name}" in
  sparket-miner-01)
    echo "COMPETITIVE_MIN_EDGE=0.10"
    echo "COMPETITIVE_CHANGE_THRESHOLD=0.08"
    echo "COMPETITIVE_MAX_MARKETS=20"
    ;;
  sparket-miner-06)
    echo "COMPETITIVE_MIN_EDGE=0.10"
    echo "COMPETITIVE_CHANGE_THRESHOLD=0.08"
    echo "COMPETITIVE_MAX_MARKETS=25"
    ;;
  sparket-miner-03|sparket-miner-05)
    echo "COMPETITIVE_MIN_EDGE=0.05"
    echo "COMPETITIVE_CHANGE_THRESHOLD=0.04"
    echo "COMPETITIVE_MAX_MARKETS=40"
    ;;
  *)
    echo "COMPETITIVE_MIN_EDGE=0.07"
    echo "COMPETITIVE_CHANGE_THRESHOLD=0.05"
    echo "COMPETITIVE_MAX_MARKETS=35"
    ;;
esac)

SPARKET_TEST_MODE=false
PYTHONUNBUFFERED=1
EOF
  echo "  Generated: ${env_path}"
}

# ----------------------------------------------------------------
# Generate per-miner YAML config
# ----------------------------------------------------------------
generate_yaml() {
  local pm2_name="$1"
  local wallet="$2"
  local hotkey="$3"
  local port="$4"
  local db_file
  db_file="$(db_file_for "$pm2_name")"
  local yaml_path
  yaml_path="$(yaml_file_for "$pm2_name")"

  cat > "$yaml_path" << EOF
# Auto-generated by run_multi_miner_sparket.sh — miner: ${pm2_name}
role: miner

chain:
  netuid: ${NETUID}

wallet:
  name: ${wallet}
  hotkey: ${hotkey}

subtensor:
  network: ${NETWORK}
  chain_endpoint: wss://entrypoint-finney.opentensor.ai:443

axon:
  host: 0.0.0.0
  port: ${port}

miner:
  allow_connection_info_from_unpermitted_validators: false
  database_filename: ${db_file}

  cadence:
    odds_seconds: 900
    outcomes_seconds: 300

  rate:
    global_per_minute: 90
    per_market_per_minute: 4

  retry:
    max_attempts: 3

  idempotency:
    bucket_seconds: 60

database:
  host: 127.0.0.1
  port: 5432
  user: sparket
  name: sparket_miner
EOF
  echo "  Generated: ${yaml_path}"
}

# ----------------------------------------------------------------
# Commands
# ----------------------------------------------------------------
start_all() {
  require_pm2
  mkdir -p "${REPO_DIR}/${LOG_DIR}"
  cd "$REPO_DIR"

  for entry in "${MINERS[@]}"; do
    parse_entry "$entry"
    echo ""
    echo "Starting: ${_PM2_NAME}  wallet=${_WALLET}  hotkey=${_HOTKEY}  port=${_PORT}  leagues=${_LEAGUES}  elo_k=${_ELO_K}"

    # Generate config files
    generate_env "$_PM2_NAME" "$_WALLET" "$_HOTKEY" "$_PORT" "$_API_PORT" "$_LEAGUES" "$_ELO_K"
    generate_yaml "$_PM2_NAME" "$_WALLET" "$_HOTKEY" "$_PORT"
    generate_wrapper "$_PM2_NAME"

    local wrapper
    wrapper="$(wrapper_for "$_PM2_NAME")"

    # Delete old process if it exists
    pm2 delete "$_PM2_NAME" 2>/dev/null || true

    # Start via wrapper script (sources .env file; avoids --env-file PM2 flag)
    pm2 start "$wrapper" \
      --name "$_PM2_NAME" \
      --interpreter bash \
      --output "${REPO_DIR}/${LOG_DIR}/${_PM2_NAME}-out.log" \
      --error  "${REPO_DIR}/${LOG_DIR}/${_PM2_NAME}-err.log"
  done

  pm2 save
  echo ""
  echo "All miners started. Run: pm2 list"
}

stop_all() {
  require_pm2
  for entry in "${MINERS[@]}"; do
    parse_entry "$entry"
    echo "Stopping: ${_PM2_NAME}"
    pm2 stop "$_PM2_NAME" 2>/dev/null || echo "  (not running)"
  done
}

restart_all() {
  require_pm2
  cd "$REPO_DIR"
  for entry in "${MINERS[@]}"; do
    parse_entry "$entry"
    echo "Restarting: ${_PM2_NAME}"
    local env_path
    env_path="$(env_file_for "$_PM2_NAME")"
    # Regenerate configs then restart
    generate_env     "$_PM2_NAME" "$_WALLET" "$_HOTKEY" "$_PORT" "$_API_PORT" "$_LEAGUES" "$_ELO_K"
    generate_yaml    "$_PM2_NAME" "$_WALLET" "$_HOTKEY" "$_PORT"
    generate_wrapper "$_PM2_NAME"
    pm2 restart "$_PM2_NAME" 2>/dev/null \
      || echo "  Not running — use 'start' first"
  done
}

status_all() {
  require_pm2
  pm2 list
}

logs_one() {
  local name="$1"
  if [ -z "$name" ]; then
    echo "Usage: $0 logs <pm2_name>"
    echo "Available miners:"
    for entry in "${MINERS[@]}"; do
      parse_entry "$entry"
      echo "  ${_PM2_NAME}  (${_WALLET}/${_HOTKEY}  port:${_PORT}  leagues:${_LEAGUES})"
    done
    exit 1
  fi
  pm2 logs "$name"
}

list_miners() {
  echo ""
  echo "Configured Sparket miners (netuid ${NETUID}, network ${NETWORK}):"
  echo ""
  printf "  %-24s %-28s %-6s %-6s %-42s %s\n" "PM2_NAME" "HOTKEY" "PORT" "ELOК" "LEAGUES" "WALLET"
  printf "  %-24s %-28s %-6s %-6s %-42s %s\n" "--------" "------" "----" "----" "-------" "------"
  for entry in "${MINERS[@]}"; do
    parse_entry "$entry"
    printf "  %-24s %-28s %-6s %-6s %-42s %s\n" \
      "$_PM2_NAME" "$_HOTKEY" "$_PORT" "$_ELO_K" "$_LEAGUES" "$_WALLET"
  done
  echo ""
  echo "External IP: ${EXTERNAL_IP}"
}

register_info() {
  require_btcli
  echo ""
  echo "=== Sparket hotkey registration checklist ==="
  echo "Netuid: ${NETUID}  Network: ${NETWORK}"
  echo ""
  for entry in "${MINERS[@]}"; do
    parse_entry "$entry"
    echo "Miner: ${_PM2_NAME}"
    echo "  Wallet: ${_WALLET}   Hotkey: ${_HOTKEY}   Port: ${_PORT}"

    # Check if hotkey is registered
    local registered
    registered=$(btcli wallet list 2>/dev/null | grep -c "$_HOTKEY" || echo "0")
    if [ "$registered" -gt 0 ]; then
      echo "  Hotkey file: FOUND locally"
    else
      echo "  Hotkey file: NOT FOUND — create with:"
      echo "    btcli wallet new_hotkey --wallet.name ${_WALLET} --wallet.hotkey ${_HOTKEY}"
    fi

    echo "  Register on-chain:"
    echo "    btcli subnets register --netuid ${NETUID} --wallet.name ${_WALLET} --wallet.hotkey ${_HOTKEY} --subtensor.network ${NETWORK}"
    echo "  Open firewall port:"
    echo "    sudo ufw allow ${_PORT}/tcp"
    echo ""
  done
}

open_firewall() {
  echo "Opening UFW ports for all miners..."
  for entry in "${MINERS[@]}"; do
    parse_entry "$entry"
    echo "  ufw allow ${_PORT}/tcp  (${_PM2_NAME})"
    sudo ufw allow "${_PORT}/tcp"
  done
  sudo ufw reload
  echo "Done. Run: sudo ufw status numbered"
}

discover_leagues() {
  # Query every miner's local SQLite DB to find ALL leagues the validator
  # is actually serving — use this to spot thin/niche leagues like "uol"
  # that you're not yet covering.
  echo ""
  echo "Discovering leagues from local SQLite databases..."
  echo "(Shows league codes, market counts, and how many miners already cover each)"
  echo ""

  local python="${PYTHON}"
  "$python" - "${REPO_DIR}" << 'PYEOF'
import sys, os, glob, sqlite3
from collections import defaultdict

repo = sys.argv[1]
dbs = glob.glob(os.path.join(repo, "*.db"))
if not dbs:
    print("  No .db files found. Miners must run at least one cycle first.")
    sys.exit(0)

league_counts  = defaultdict(int)   # league → total markets across all DBs
league_miners  = defaultdict(set)   # league → set of DB filenames covering it

for db_path in dbs:
    miner_name = os.path.basename(db_path)
    try:
        conn = sqlite3.connect(db_path)
        cur  = conn.cursor()
        # Try common column names the validator schema might use
        for col in ("league", "sport", "league_id"):
            try:
                cur.execute(f"SELECT {col}, COUNT(*) FROM markets GROUP BY {col}")
                rows = cur.fetchall()
                if rows:
                    for league, cnt in rows:
                        if league:
                            league_counts[str(league).lower()] += cnt
                            league_miners[str(league).lower()].add(miner_name)
                    break
            except sqlite3.OperationalError:
                continue
        conn.close()
    except Exception as e:
        print(f"  [skip {miner_name}: {e}]")

if not league_counts:
    print("  No market data found yet — miners may not have synced.")
    sys.exit(0)

sorted_leagues = sorted(league_counts.items(), key=lambda x: x[1], reverse=True)

GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

print(f"  {BOLD}{'LEAGUE':<20} {'MARKETS':>8}  {'MINERS_COVERING':>16}  NOTE{RESET}")
print("  " + "─" * 65)
for league, cnt in sorted_leagues:
    n_miners = len(league_miners[league])
    note = ""
    if n_miners == 0:
        note = f"{GREEN}← NOT COVERED by any miner!{RESET}"
    elif n_miners == 1:
        note = f"{YELLOW}← only 1 miner{RESET}"
    if cnt < 20:
        note = f"{GREEN}← THIN MARKET {note}{RESET}"
    colour = GREEN if n_miners <= 1 else ""
    print(f"  {colour}{league:<20}{RESET} {cnt:>8}  {n_miners:>16}  {note}")

print()
print("  Tip: leagues with low MARKETS count and low MINERS_COVERING = highest Marginal opportunity.")
print(f"  Add them to niche miners with: COMPETITIVE_LEAGUES=uol,<other_thin_league>")
PYEOF
  echo ""
}

# ----------------------------------------------------------------
# Entrypoint
# ----------------------------------------------------------------
case "${1:-}" in
  start)     start_all ;;
  stop)      stop_all ;;
  restart)   restart_all ;;
  status)    status_all ;;
  logs)      logs_one "${2:-}" ;;
  list)      list_miners ;;
  register)  register_info ;;
  firewall)  open_firewall ;;
  discover)  discover_leagues ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs <name>|list|register|firewall|discover}"
    echo ""
    list_miners
    exit 1
    ;;
esac
