"""CompetitiveMinerService — production replacement for BaseMiner.

Architecture:
  ┌───────────────────────────────────────────────────────────────┐
  │                   CompetitiveMinerService                     │
  │                                                               │
  │  ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐   │
  │  │  OddsLoop    │  │ OutcomeLoop   │  │  TrainingLoop    │   │
  │  │  (15 min)    │  │  (5 min)      │  │  (on new result) │   │
  │  └──────┬───────┘  └──────┬────────┘  └────────┬─────────┘   │
  │         │                 │                    │              │
  │  EventSelector          ESPN           ModelRegistry          │
  │  EloRatings             Fetcher        (LightGBM+ISO)         │
  │  Features               Results                               │
  │  ValidatorClient ────────────────────────────────────────►    │
  └───────────────────────────────────────────────────────────────┘

Scoring pillar mapping:
  Uniqueness  ← features are 100% independent of market odds
  Edge        ← Elo + form signal vs closing line (CLV)
  Accuracy    ← isotonic calibration keeps Brier < 0.30 floor
  Timeliness  ← submits immediately when model disagrees with last submission
  Marginal    ← EventSelector focuses on thin markets (fewer miners)

To wire into the miner entrypoint, add to sparket/entrypoints/miner.py:

    from sparket.miner.competitive.service import CompetitiveMinerService
    ...
    svc = CompetitiveMinerService(miner)
    svc.start()
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import bittensor as bt
import numpy as np

from sparket.miner.client import ValidatorClient
from sparket.miner.base.fetchers.espn import ESPNFetcher
from sparket.miner.competitive.elo import EloRatings
from sparket.miner.competitive.event_selector import EventSelector
from sparket.miner.competitive.features import build_feature_vector
from sparket.miner.competitive.model import ModelRegistry

# ---------------------------------------------------------------------------
# Config from env
# ---------------------------------------------------------------------------

_ODDS_INTERVAL    = int(os.getenv("COMPETITIVE_ODDS_INTERVAL", "900"))    # 15 min
_OUTCOME_INTERVAL = int(os.getenv("COMPETITIVE_OUTCOME_INTERVAL", "300")) # 5 min
_BATCH_SIZE       = int(os.getenv("COMPETITIVE_BATCH_SIZE", "75"))

# If our calibrated probability deviates from last submitted by >= this, submit early
_EARLY_TRIGGER_DELTA = 0.025


class CompetitiveMinerService:
    """Drop-in replacement for BaseMiner.

    Usage:
        svc = CompetitiveMinerService(miner)
        svc.start()                # non-blocking; runs background loops
        ...
        svc.stop()
    """

    def __init__(self, miner: Any) -> None:
        self.miner = miner
        self._hotkey: str = miner.wallet.hotkey.ss58_address

        self._client = ValidatorClient(
            wallet=miner.wallet,
            metagraph=miner.metagraph,
            get_validator_endpoint=lambda: getattr(miner, "validator_endpoint", None),
        )
        self._game_sync = getattr(miner, "game_sync", None)
        self._espn = ESPNFetcher(cache_ttl_seconds=1800)

        self._elo = EloRatings()
        self._elo.load()

        self._models = ModelRegistry()
        self._selector = EventSelector()

        # last submitted probability per market_id — for early-trigger delta check
        self._last_prob: Dict[int, float] = {}

        self._running = False
        self._tasks: List[asyncio.Task] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start background loops (non-blocking — runs in daemon thread)."""
        if self._running:
            return
        self._running = True
        import threading
        loop = asyncio.new_event_loop()
        self._loop = loop

        def _runner():
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._run())

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        bt.logging.info({"competitive_service": "started", "hotkey": self._hotkey[:12]})

    def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        self._elo.save()
        self._models.save_all()
        bt.logging.info({"competitive_service": "stopped"})

    async def _run(self) -> None:
        try:
            self._tasks = [
                asyncio.create_task(self._odds_loop()),
                asyncio.create_task(self._outcome_loop()),
            ]
            await asyncio.gather(*self._tasks, return_exceptions=True)
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Odds loop
    # ------------------------------------------------------------------

    async def _odds_loop(self) -> None:
        """Main pricing loop — runs every COMPETITIVE_ODDS_INTERVAL seconds."""
        while self._running:
            t0 = time.monotonic()
            try:
                await self._run_odds_cycle()
            except Exception as exc:
                bt.logging.warning({"competitive_odds_cycle_error": str(exc)})
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0.0, _ODDS_INTERVAL - elapsed))

    async def _run_odds_cycle(self) -> None:
        # 1. Sync game data from validator
        if self._game_sync:
            try:
                await self._game_sync.sync_once()
            except Exception as e:
                bt.logging.debug({"competitive_sync_error": str(e)})

        # 2. Get all active markets
        all_markets: List[Dict] = []
        if self._game_sync:
            all_markets = await self._game_sync.get_active_markets()

        if not all_markets:
            bt.logging.debug({"competitive_odds": "no_active_markets"})
            return

        # 3. Filter and rank via EventSelector
        markets = self._selector.select(all_markets)
        if not markets:
            bt.logging.debug({"competitive_odds": "no_markets_after_selection"})
            return

        # 4. Price each market, collect into batch
        now = datetime.now(timezone.utc)
        batch: List[Dict] = []
        skipped = 0
        early_triggers = 0
        total_submitted = 0
        batch_count = 0

        for market in markets:
            try:
                priced = await self._price_market(market)
                if priced is None:
                    skipped += 1
                    continue

                market_id = int(market["market_id"])
                kind = market.get("kind", "moneyline").lower()

                # Early-trigger: check if probability moved enough to justify
                # an immediate submission outside the normal cadence
                if kind == "moneyline":
                    new_p = priced["prices"][0]["imp_prob"]
                    last_p = self._last_prob.get(market_id, -1.0)
                    if last_p >= 0 and abs(new_p - last_p) < _EARLY_TRIGGER_DELTA:
                        skipped += 1  # no meaningful change — skip this cycle
                        continue
                    else:
                        if last_p >= 0:
                            early_triggers += 1
                        self._last_prob[market_id] = new_p

                submission = {
                    "market_id": market_id,
                    "kind": kind,
                    "priced_at": now.isoformat(),
                    "prices": priced["prices"],
                }
                batch.append(submission)

                # Flush batch when full
                if len(batch) >= _BATCH_SIZE:
                    ok = await self._submit_odds_batch(batch)
                    if ok:
                        total_submitted += len(batch)
                    batch_count += 1
                    batch = []

            except Exception as e:
                skipped += 1
                bt.logging.debug({
                    "competitive_price_error": str(e),
                    "market_id": market.get("market_id"),
                })

        # Flush remaining
        if batch:
            ok = await self._submit_odds_batch(batch)
            if ok:
                total_submitted += len(batch)
            batch_count += 1

        bt.logging.info({
            "competitive_odds_cycle": {
                "markets_selected": len(markets),
                "submitted": total_submitted,
                "skipped": skipped,
                "early_triggers": early_triggers,
                "batches": batch_count,
            }
        })

    async def _price_market(self, market: Dict) -> Optional[Dict]:
        """Price a single market using Elo + LightGBM model."""
        league  = (market.get("league") or market.get("sport") or "").lower()
        home    = market.get("home_team", "")
        away    = market.get("away_team", "")
        kind    = (market.get("kind") or "moneyline").lower()
        line    = market.get("line")

        if not home or not away:
            return None

        # Fetch ESPN stats (cached 30 min)
        home_stats = await self._espn.get_team_stats(home, league.upper())
        away_stats = await self._espn.get_team_stats(away, league.upper())

        # Build feature vector
        features = build_feature_vector(
            league=league,
            home_team=home,
            away_team=away,
            home_stats=home_stats,
            away_stats=away_stats,
            elo=self._elo,
        )

        # Price via model
        priced = self._models.get(league).price_market(features, kind, line)
        return priced

    async def _submit_odds_batch(self, submissions: List[Dict]) -> bool:
        """Submit a batch of priced markets to the validator."""
        token = self._token()
        payload: Dict[str, Any] = {
            "miner_hotkey": self._hotkey,
            "submissions": submissions,
        }
        if token:
            payload["token"] = token
        return await self._client.submit_odds(payload)

    # ------------------------------------------------------------------
    # Outcome loop
    # ------------------------------------------------------------------

    async def _outcome_loop(self) -> None:
        """Check for finished games every COMPETITIVE_OUTCOME_INTERVAL seconds."""
        while self._running:
            t0 = time.monotonic()
            try:
                await self._run_outcome_cycle()
            except Exception as exc:
                bt.logging.warning({"competitive_outcome_cycle_error": str(exc)})
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0.0, _OUTCOME_INTERVAL - elapsed))

    async def _run_outcome_cycle(self) -> None:
        """Submit outcomes for finished events and update Elo + model."""
        finished = await self._get_finished_events()
        if not finished:
            return

        submitted = 0
        for event in finished:
            try:
                result = await self._espn.get_result(event)
                if result is None or not result.is_final:
                    continue

                # Build outcome payload
                payload = self._build_outcome_payload(event, result)
                ok = await self._client.submit_outcome(payload)
                if ok:
                    submitted += 1

                # Update Elo ratings from this result
                league  = (event.get("league") or event.get("sport") or "").lower()
                home    = event.get("home_team", "")
                away    = event.get("away_team", "")
                h_score = result.home_score or 0
                a_score = result.away_score or 0

                if home and away and league:
                    self._elo.update(league, home, away, h_score, a_score)

                    # Feed resolved result into model training buffer
                    home_stats = await self._espn.get_team_stats(home, league.upper())
                    away_stats = await self._espn.get_team_stats(away, league.upper())
                    features = build_feature_vector(
                        league, home, away, home_stats, away_stats, self._elo
                    )
                    self._models.add_resolved(league, features, float(h_score), float(a_score))

            except Exception as e:
                bt.logging.debug({
                    "competitive_outcome_error": str(e),
                    "event_id": event.get("event_id"),
                })

        if submitted > 0:
            # Persist updated Elo and models after each outcome cycle
            self._elo.save()
            self._models.save_all()
            bt.logging.info({"competitive_outcomes_submitted": submitted})

    async def _get_finished_events(self) -> List[Dict]:
        if not self._game_sync:
            return []
        try:
            from sparket.miner.database.repository import get_past_events
            return await get_past_events(self._game_sync.database)
        except Exception:
            return []

    def _build_outcome_payload(self, event: Dict, result: Any) -> Dict:
        now = datetime.now(timezone.utc)
        payload: Dict[str, Any] = {
            "event_id": int(event.get("event_id", 0)),
            "miner_hotkey": self._hotkey,
            "result": result.winner if hasattr(result, "winner") else (
                "home" if (result.home_score or 0) > (result.away_score or 0) else "away"
            ),
            "score_home": result.home_score,
            "score_away": result.away_score,
            "ts_submit": now.isoformat(),
        }
        token = self._token()
        if token:
            payload["token"] = token
        return payload

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _token(self) -> Optional[str]:
        endpoint = getattr(self.miner, "validator_endpoint", None) or {}
        return endpoint.get("token") if isinstance(endpoint, dict) else None

    def model_summary(self) -> Dict:
        """Return a summary of model readiness per league — for monitoring."""
        return {
            league: {
                "lgb_ready": self._models.get(league).is_ready(),
                "n_trained": self._models.get(league)._n_trained,
                "elo_home": round(self._elo.get(league, "---"), 1),
            }
            for league in self._selector.leagues()
        }
