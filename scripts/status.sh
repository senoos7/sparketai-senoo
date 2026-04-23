#!/bin/bash
# ============================================================
# status.sh — Sparket miner runtime status at a glance
#
# Shows:
#   1. PM2 process table
#   2. Per-miner KPI snapshot  (~/.sparket/kpi_*.json)
#   3. Optionally: on-chain weights (pass --weights)
#
# Usage:
#   bash scripts/status.sh
#   bash scripts/status.sh --weights            # also run check_weights.py
#   bash scripts/status.sh --weights --vps-ip 1.2.3.4
# ============================================================

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-${REPO_DIR}/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then PYTHON="$(which python3)"; fi

BOLD="\033[1m"
GREEN="\033[32m"
CYAN="\033[36m"
YELLOW="\033[33m"
DIM="\033[2m"
RED="\033[31m"
RESET="\033[0m"

SHOW_WEIGHTS=false
VPS_IP=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --weights) SHOW_WEIGHTS=true; shift ;;
    --vps-ip)  VPS_IP="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# ----------------------------------------------------------------
# 1. PM2 process table
# ----------------------------------------------------------------
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  PM2 Process Table${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
if command -v pm2 &>/dev/null; then
  pm2 list
else
  echo -e "  ${RED}pm2 not found${RESET}"
fi

# ----------------------------------------------------------------
# 2. KPI snapshots
# ----------------------------------------------------------------
KPI_DIR="${HOME}/.sparket"
KPI_FILES=("${KPI_DIR}"/kpi_*.json)

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  Miner KPI Snapshots  (${KPI_DIR}/kpi_*.json)${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"

if [[ ! -d "$KPI_DIR" ]] || [[ "${KPI_FILES[0]}" == "${KPI_DIR}/kpi_*.json" ]]; then
  echo -e "  ${YELLOW}No KPI files found yet.${RESET} They appear after the first $COMPETITIVE_KPI_EXPORT_EVERY cycles."
  echo -e "  ${DIM}(default: 12 cycles × 15 min = ~3 hours after first start)${RESET}"
  echo ""
else
  for kpi_file in "${KPI_FILES[@]}"; do
    [[ -f "$kpi_file" ]] || continue
    echo ""
    hotkey_slug="$(basename "$kpi_file" .json | sed 's/^kpi_//')"
    echo -e "  ${CYAN}${BOLD}── ${hotkey_slug} ──${RESET}"

    # Use python to pretty-print the key fields
    "$PYTHON" - "$kpi_file" << 'PYEOF'
import sys, json
from pathlib import Path
f = Path(sys.argv[1])
try:
    d = json.loads(f.read_text())
except Exception as e:
    print(f"  [error reading file: {e}]")
    sys.exit(0)

ts   = d.get("ts_utc", "?")
hk   = d.get("hotkey", "?")
prof = d.get("profile_id", "?")

cy   = d.get("cycles_total", 0)
ms   = d.get("markets_seen", 0)
msub = d.get("markets_submitted", 0)
mskl = d.get("markets_skipped_low_change", 0)
srate= d.get("submit_rate", 0.0)
lcr  = d.get("low_change_skip_rate", 0.0)

ba   = d.get("odds_batches_attempted", 0)
bs   = d.get("odds_batches_succeeded", 0)
bf   = d.get("odds_batches_failed", 0)
bsr  = d.get("batch_success_rate", 0.0)

oes  = d.get("outcome_events_seen", 0)
osub = d.get("outcomes_submitted", 0)
ofail= d.get("outcomes_failed", 0)
onespm=d.get("outcomes_skipped_no_espn_match", 0)
onf  = d.get("outcomes_skipped_not_final", 0)
osr  = d.get("outcome_submit_rate", 0.0)

ml_s = d.get("kind_moneyline_seen", 0)
sp_s = d.get("kind_spread_seen", 0)
to_s = d.get("kind_total_seen", 0)
ml_x = d.get("kind_moneyline_submitted", 0)
sp_x = d.get("kind_spread_submitted", 0)
to_x = d.get("kind_total_submitted", 0)

GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
DIM    = "\033[2m"
RESET  = "\033[0m"

batch_col = GREEN if bsr >= 0.9 else (YELLOW if bsr >= 0.5 else RED)
sub_col   = GREEN if msub > 0 else RED

print(f"  As of:        {ts}")
print(f"  Hotkey:       {hk[:20]}…  profile={prof}")
print(f"  Cycles:       {cy}")
print()
print(f"  {'ODDS':}")
print(f"    Markets seen:       {ms:>7}   submitted: {sub_col}{msub:>7}{RESET}  submit_rate={srate:.4f}")
print(f"    Skipped low-change: {mskl:>7}   skip_rate: {lcr:.4f}")
print(f"    Batches:            {DIM}attempted={ba}  succeeded={bs}  failed={bf}{RESET}  {batch_col}success={bsr:.2%}{RESET}")
print(f"    Kinds seen:         moneyline={ml_s}  spread={sp_s}  total={to_s}")
print(f"    Kinds submitted:    moneyline={ml_x}  spread={sp_x}  total={to_x}")
print()
print(f"  {'OUTCOMES':}")
print(f"    Events seen:   {oes:>6}   submitted: {GREEN}{osub:>6}{RESET}  rate={osr:.4f}")
print(f"    Failed:        {ofail:>6}   skipped (no ESPN): {onespm}  (not final): {onf}")
PYEOF

    echo ""
    echo -e "  ${DIM}File: ${kpi_file}${RESET}"
    echo ""
  done
fi

# ----------------------------------------------------------------
# 3. Recent log tail (last 10 lines per miner from out.log)
# ----------------------------------------------------------------
LOG_DIR="${REPO_DIR}/sparket/logs/pm2-mainnet"
if [[ -d "$LOG_DIR" ]]; then
  echo ""
  echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo -e "${BOLD}  Recent Log Tails  (last 5 lines each)${RESET}"
  echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  for log_file in "${LOG_DIR}"/*-out.log; do
    [[ -f "$log_file" ]] || continue
    name="$(basename "$log_file" -out.log)"
    echo ""
    echo -e "  ${CYAN}${name}${RESET}"
    tail -n 5 "$log_file" | sed 's/^/    /'
  done
  echo ""
fi

# ----------------------------------------------------------------
# 4. On-chain weights (optional)
# ----------------------------------------------------------------
if $SHOW_WEIGHTS; then
  echo ""
  echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo -e "${BOLD}  On-Chain Weights  (netuid 57, finney)${RESET}"
  echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo ""
  if [[ -n "$VPS_IP" ]]; then
    "$PYTHON" "${REPO_DIR}/scripts/check_weights.py" --vps-ip "$VPS_IP"
  else
    "$PYTHON" "${REPO_DIR}/scripts/check_weights.py"
  fi
fi

echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
