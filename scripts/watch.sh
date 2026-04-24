#!/bin/bash
# ============================================================
# watch.sh — Live Sparket miner submission dashboard
#
# Usage:
#   bash scripts/watch.sh              # refresh every 30s
#   bash scripts/watch.sh --interval 10
#   bash scripts/watch.sh --once       # print once and exit
# ============================================================

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-${REPO_DIR}/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then PYTHON="$(which python3)"; fi
LOG_DIR="${REPO_DIR}/sparket/logs/pm2-mainnet"
KPI_DIR="${HOME}/.sparket"

INTERVAL=30
ONCE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interval|-i) INTERVAL="$2"; shift 2 ;;
    --once)        ONCE=true; shift ;;
    *) shift ;;
  esac
done

# ----------------------------------------------------------------
# Core render — called every tick
# ----------------------------------------------------------------
render() {
"$PYTHON" - "$LOG_DIR" "$KPI_DIR" << 'PYEOF'
import sys, os, json, glob, re
from datetime import datetime, timezone
from pathlib import Path

log_dir = Path(sys.argv[1])
kpi_dir = Path(sys.argv[2])
now_utc = datetime.now(timezone.utc)

BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def age(ts_str):
    """Return human-readable age like '2m ago'."""
    try:
        t = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        sec = int((now_utc - t).total_seconds())
        if sec < 0: return "just now"
        if sec < 60: return f"{sec}s ago"
        if sec < 3600: return f"{sec//60}m ago"
        return f"{sec//3600}h ago"
    except Exception:
        return "?"

def colour_rate(v, lo=0.5, hi=0.9):
    if v >= hi: return GREEN
    if v >= lo: return YELLOW
    return RED

def colour_brier(accuracy):
    """Brier is roughly 1-accuracy. Green = good accuracy."""
    if accuracy >= 0.48: return GREEN
    if accuracy >= 0.40: return YELLOW
    return RED

# ── Header ───────────────────────────────────────────────────
width = 100
print(f"\n{BOLD}{'━'*width}{RESET}")
print(f"{BOLD}  Sparket Miner Dashboard  —  {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}{RESET}")
print(f"{BOLD}{'━'*width}{RESET}")

# ── PM2 process statuses ─────────────────────────────────────
import subprocess
pm2_status = {}
try:
    result = subprocess.run(
        ["pm2", "jlist"], capture_output=True, text=True, timeout=5
    )
    procs = json.loads(result.stdout)
    for p in procs:
        name = p.get("name", "")
        status = p.get("pm2_env", {}).get("status", "?")
        restarts = p.get("pm2_env", {}).get("restart_time", 0)
        mem = p.get("monit", {}).get("memory", 0) // (1024*1024)
        pm2_status[name] = {"status": status, "restarts": restarts, "mem_mb": mem}
except Exception:
    pass

# ── KPI files ────────────────────────────────────────────────
kpi_files = sorted(kpi_dir.glob("kpi_*.json"))

if not kpi_files:
    print(f"\n  {YELLOW}No KPI files yet — miners need ~12 cycles (~3h) to export first snapshot.{RESET}")
    print(f"  {DIM}Until then, use: pm2 logs sparket-miner-01 | grep competitive_odds_cycle{RESET}\n")
else:
    # Table header
    print()
    print(f"  {BOLD}{'MINER':<24} {'ST':>2} {'CY':>4} {'SEEN':>6} {'SUB':>5} "
          f"{'S_RATE':>7} {'BCHOK':>6} {'O_SUB':>6} {'O_RATE':>6} {'AGE':>9}  LEAGUES{RESET}")
    print("  " + "─"*105)

    for kpi_file in kpi_files:
        slug = kpi_file.stem.replace("kpi_", "")
        try:
            d = json.loads(kpi_file.read_text())
        except Exception:
            continue

        ts   = d.get("ts_utc", "")
        cy   = d.get("cycles_total", 0)
        ms   = d.get("markets_seen", 0)
        msub = d.get("markets_submitted", 0)
        srate= d.get("submit_rate", 0.0)
        ba   = d.get("odds_batches_attempted", 0)
        bs   = d.get("odds_batches_succeeded", 0)
        bf   = d.get("odds_batches_failed", 0)
        osub = d.get("outcomes_submitted", 0)
        orate= d.get("outcome_submit_rate", 0.0)
        leagues = ",".join(d.get("config", {}).get("leagues", []))

        # PM2 name heuristic — match slug (hotkey) to pm2 process
        pm2_name = ""
        pm2_info = {}
        for pname, pinfo in pm2_status.items():
            if "sparket-miner" in pname:
                pm2_name = pname
                pm2_info = pinfo
                # Try to match by checking if slug appears in the env file name
                if slug in pname or pname.replace("sparket-miner-0", "sparket-miner-") in slug:
                    break

        # Find matching pm2 by looking at env files
        for pname in pm2_status:
            env_file = kpi_dir.parent / f".env.{pname}"
            if env_file.exists():
                content = env_file.read_text()
                if f"SPARKET_WALLET__HOTKEY={slug}" in content:
                    pm2_info = pm2_status[pname]
                    pm2_name = pname
                    break

        # Also try matching by the out log file
        if not pm2_name:
            for log_file in log_dir.glob("*-out.log"):
                pname = log_file.stem.replace("-out", "")
                # Read last few lines to see if this hotkey appears
                try:
                    lines = log_file.read_text().split("\n")[-50:]
                    if any(slug[:12] in line for line in lines):
                        pm2_info = pm2_status.get(pname, {})
                        pm2_name = pname
                        break
                except Exception:
                    pass

        st     = pm2_info.get("status", "?")
        mem    = pm2_info.get("mem_mb", 0)
        rst    = pm2_info.get("restarts", 0)

        # Status colour
        if st == "online":
            st_col = GREEN
            st_icon = "✓"
        elif st in ("stopped", "stopping"):
            st_col = DIM
            st_icon = "■"
        elif st in ("errored", "error"):
            st_col = RED
            st_icon = "✗"
        else:
            st_col = YELLOW
            st_icon = "?"

        bsr   = bs / max(ba, 1)
        rc    = colour_rate(bsr)
        sc    = colour_rate(srate, lo=0.01, hi=0.05)

        rst_warn = f" {YELLOW}↺{rst}{RESET}" if rst > 3 else ""

        # Warn when KPI is stale (> 4 hours = missed at least one export)
        kpi_age_str = age(ts)
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            kpi_stale = (now_utc - t).total_seconds() > 4 * 3600
        except Exception:
            kpi_stale = True
        age_col = YELLOW if kpi_stale else DIM
        age_note = " ←stale" if kpi_stale else ""

        print(
            f"  {CYAN}{slug:<24}{RESET} "
            f"{st_col}{st_icon}{RESET} "
            f"{cy:>4} {ms:>6} {sc}{msub:>5}{RESET} "
            f"{sc}{srate:>6.3f}{RESET} "
            f"{rc}{bsr:>5.0%}{RESET} "
            f"{osub:>6} {orate:>5.2f} "
            f"{age_col}{kpi_age_str:>9}{age_note}{RESET}  "
            f"{DIM}{leagues[:35]}{RESET}"
            f"{rst_warn}"
        )

    print()
    print(f"  {DIM}Columns: CY=cycles  SEEN=markets  SUB=submitted  S_RATE=submit_rate  "
          f"BCHOK=batch_success  O_SUB=outcomes  O_RATE=outcome_rate  AGE=kpi_age{RESET}")

# ── Live log tail: last competitive_odds_cycle per miner ─────
print()
print(f"{BOLD}{'━'*width}{RESET}")
print(f"{BOLD}  Recent Cycle Activity  (latest competitive_odds_cycle per miner){RESET}")
print(f"{BOLD}{'━'*width}{RESET}")

if log_dir.exists():
    for log_file in sorted(log_dir.glob("*-out.log")):
        miner_name = log_file.stem.replace("-out", "")
        try:
            lines = log_file.read_text().split("\n")
        except Exception:
            continue

        # Find last relevant log lines
        last_cycle   = None
        last_outcome = None
        last_token   = None   # token_invalid (soft — resolves after validator push)
        last_reject  = None   # hard rejection (e.g. rate limit)
        for line in reversed(lines):
            # Strip ANSI codes so regex works cleanly
            clean = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
            if "competitive_odds_cycle" in clean and last_cycle is None:
                last_cycle = clean
            if "competitive_outcomes_submitted" in clean and last_outcome is None:
                last_outcome = clean
            if "token_invalid" in clean and last_token is None:
                last_token = clean
            if "submit_odds_rejected" in clean and "token_invalid" not in clean and last_reject is None:
                last_reject = clean
            if last_cycle and last_outcome:
                break

        if not last_cycle and not last_outcome and not last_token:
            continue

        print(f"\n  {CYAN}{miner_name}{RESET}")

        if last_cycle:
            # Handle both Python repr ({'key': val}) and JSON ({"key": val}) formats
            def _num(key, line):
                m = re.search(rf"['\"]?{key}['\"]?\s*:\s*(\d+)", line)
                return int(m.group(1)) if m else None

            sub  = _num("submitted",        last_cycle)
            skip = _num("skipped_low_change", last_cycle)
            cyc  = _num("cycle",            last_cycle)
            sel  = _num("markets_selected", last_cycle)
            bat  = _num("batches",          last_cycle)
            cumul= _num("total_submitted_cumul", last_cycle)

            sub_col  = GREEN if sub and sub > 0 else YELLOW
            ts_m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", last_cycle)
            ts_s = ts_m.group(1) if ts_m else ""
            print(
                f"    {DIM}{ts_s}{RESET}  "
                f"cycle={cyc}  selected={sel}  "
                f"submitted={sub_col}{sub}{RESET}  "
                f"skipped_low={skip}  batches={bat}"
                + (f"  cumul={cumul}" if cumul is not None else "")
            )
        else:
            print(f"    {YELLOW}No odds cycle logged yet — waiting for first cycle{RESET}")

        if last_outcome:
            m = re.search(r"['\"]?competitive_outcomes_submitted['\"]?\s*:\s*(\d+)", last_outcome)
            n = m.group(1) if m else "?"
            ts_m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", last_outcome)
            ts_s = ts_m.group(1) if ts_m else ""
            print(f"    {DIM}{ts_s}{RESET}  {GREEN}outcomes_submitted={n}{RESET}")

        if last_token:
            ts_m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", last_token)
            ts_s = ts_m.group(1) if ts_m else ""
            print(f"    {YELLOW}⚠ {ts_s}  token_invalid — will self-heal when validator pushes (wait ~15 min){RESET}")

        if last_reject:
            ts_m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", last_reject)
            ts_s = ts_m.group(1) if ts_m else ""
            # Truncate and clean the error message
            msg = re.sub(r"\x1b\[[0-9;]*m", "", last_reject)[-120:]
            print(f"    {RED}✗ {ts_s}  {msg}{RESET}")

print()
print(f"{BOLD}{'━'*width}{RESET}")
print(f"  {DIM}Refresh interval: see --interval flag  |  Quit: Ctrl-C{RESET}\n")
PYEOF
}

# ----------------------------------------------------------------
# Run once or loop
# ----------------------------------------------------------------
if $ONCE; then
  render
else
  # Use watch if available (handles terminal resize), else manual loop
  if command -v watch &>/dev/null; then
    # Export render function vars and call this script with --once
    watch -n "$INTERVAL" -c "bash \"$(realpath "$0")\" --once"
  else
    while true; do
      clear
      render
      sleep "$INTERVAL"
    done
  fi
fi
