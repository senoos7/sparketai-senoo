"""Competitive miner service — production replacement for BaseMiner.

Wiring into miner entrypoint:

    from sparket.miner.competitive.service import CompetitiveMinerService

    # After miner is created, before miner.run():
    svc = CompetitiveMinerService(miner)
    svc.start()
"""
from sparket.miner.competitive.service import CompetitiveMinerService
from sparket.miner.competitive.elo import EloRatings
from sparket.miner.competitive.model import ModelRegistry
from sparket.miner.competitive.event_selector import EventSelector

__all__ = [
    "CompetitiveMinerService",
    "EloRatings",
    "ModelRegistry",
    "EventSelector",
]
