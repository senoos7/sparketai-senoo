"""
Check validator-set weights for all miners on the Sparket subnet (netuid 57 on testnet).

Shows: UID, raw weight, weight%, incentive, axon IP:port, active status.

Usage:
    cd ~/sparket-ai
    python scripts/check_weights.py
    python scripts/check_weights.py --netuid 57
    python scripts/check_weights.py --network finney --netuid <mainnet-netuid>
    python scripts/check_weights.py --uids 0,1,2,3   # filter specific UIDs
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import bittensor as bt

# Your VPS external IP — miners registered from this IP are highlighted as "MINE"
# Update this to match your miner's server IP.
YOUR_VPS_IP = ""


def main(netuid: int, network: str, filter_uids: list[int] | None) -> None:
    print(f"\nConnecting to Bittensor ({network})...")
    sub  = bt.Subtensor(network=network)
    meta = sub.metagraph(netuid=netuid)
    print(f"Metagraph: netuid={netuid}  n={meta.n}  block={meta.block}\n")

    # Weights: list of (validator_uid, [(miner_uid, weight), ...])
    raw_weights = sub.weights(netuid=netuid)

    # Aggregate: sum weights each miner received across all validators
    weight_sum: dict[int, float] = {}
    for _validator_uid, miner_weights in raw_weights:
        for miner_uid, w in miner_weights:
            weight_sum[miner_uid] = weight_sum.get(miner_uid, 0.0) + float(w)

    total_weight = sum(weight_sum.values()) or 1.0

    # Build rows
    rows = []
    for uid in range(meta.n):
        if filter_uids and uid not in filter_uids:
            continue

        raw_w     = weight_sum.get(uid, 0.0)
        pct       = raw_w / total_weight * 100
        incentive = float(meta.I[uid])
        hotkey    = meta.hotkeys[uid]
        axon      = meta.axons[uid]
        ip_port   = f"{axon.ip}:{axon.port}" if axon.ip not in {"", "0.0.0.0", "[::]"} else "—"
        is_mine   = bool(YOUR_VPS_IP) and axon.ip == YOUR_VPS_IP
        active    = bool(meta.active[uid])

        rows.append((uid, raw_w, pct, incentive, hotkey[:12] + "…", ip_port, is_mine, active))

    # Sort by weight descending, non-zero first
    rows.sort(key=lambda r: r[1], reverse=True)

    BOLD  = "\033[1m"
    GREEN = "\033[32m"
    CYAN  = "\033[36m"
    DIM   = "\033[2m"
    RESET = "\033[0m"

    header = (
        f"  {'UID':>4}  {'RawWeight':>11}  {'Weight%':>8}  "
        f"{'Incentive':>10}  {'Active':>6}  {'Hotkey':>14}  {'Axon IP:Port'}"
    )
    print(BOLD + header + RESET)
    print("  " + "─" * 90)

    for uid, raw_w, pct, incentive, hotkey_short, ip_port, is_mine, active in rows:
        colour = CYAN + BOLD if is_mine else (DIM if raw_w == 0 else "")
        marker = " ◀ MINE" if is_mine else ""
        active_str = "yes" if active else "no"
        print(
            f"{colour}"
            f"  {uid:>4}  {raw_w:>11.1f}  {pct:>7.4f}%  {incentive:>10.6f}"
            f"  {active_str:>6}  {hotkey_short:>14}  {ip_port}"
            f"{RESET}{GREEN}{marker}{RESET}"
        )

    # Your miners summary
    mine_rows = [r for r in rows if r[6]]
    if mine_rows:
        print(f"\n{BOLD}── Your miners ──────────────────────────────────{RESET}")
        total_mine_pct       = sum(r[2] for r in mine_rows)
        total_mine_incentive = sum(r[3] for r in mine_rows)
        for uid, raw_w, pct, incentive, hotkey_short, ip_port, _, active in mine_rows:
            active_str = "yes" if active else "no"
            print(
                f"  UID {uid:>3}  weight={pct:.4f}%  incentive={incentive:.6f}"
                f"  active={active_str}  axon={ip_port}"
            )
        print(f"  {'TOTAL':>5}  weight={total_mine_pct:.4f}%  incentive={total_mine_incentive:.6f}")

    # Validator-weight breakdown (who is setting weights)
    if raw_weights:
        print(f"\n{BOLD}── Validator weight coverage ────────────────────{RESET}")
        for val_uid, miner_weights in raw_weights:
            n_nonzero = sum(1 for _, w in miner_weights if float(w) > 0)
            total_val_w = sum(float(w) for _, w in miner_weights)
            val_hotkey = meta.hotkeys[val_uid][:12] + "…" if val_uid < meta.n else "?"
            print(
                f"  validator UID {val_uid:>4}  ({val_hotkey})"
                f"  {n_nonzero} miners weighted  total_w={total_val_w:.1f}"
            )

    print()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Check Sparket miner weights from metagraph")
    p.add_argument(
        "--netuid", type=int, default=57,
        help="Subnet UID (default: 57 testnet; override for mainnet)",
    )
    p.add_argument(
        "--network", type=str, default="finney",
        choices=["finney", "test", "local"],
        help="Bittensor network (default: finney)",
    )
    p.add_argument(
        "--uids", type=str, default="",
        help="Comma-separated UIDs to show (default: all)",
    )
    p.add_argument(
        "--vps-ip", type=str, default="",
        help="Your miner's VPS IP to highlight as MINE (overrides hard-coded YOUR_VPS_IP)",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.vps_ip:
        YOUR_VPS_IP = args.vps_ip  # noqa: F811  (module-level override for display)

    filter_uids = None
    if args.uids.strip():
        try:
            filter_uids = [int(u.strip()) for u in args.uids.split(",")]
        except ValueError:
            print("Invalid --uids value. Use comma-separated integers.")
            sys.exit(1)

    main(args.netuid, args.network, filter_uids)
