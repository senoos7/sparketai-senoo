"""Prediction model: LightGBM + isotonic calibration.

Pipeline:
  1. Collect labeled training rows (features + outcome) from local DB
     as submitted predictions get resolved.
  2. Train LightGBM binary classifier on home win probability.
  3. Apply isotonic regression calibration layer.
  4. Use calibrated P(home wins) to price all three market types.

Bootstrap:
  When fewer than MIN_TRAIN_SAMPLES are available, fall back to
  the Elo-only probability (still independent — still earns Uniqueness).

Calibration importance:
  Brier > 0.30 → SkillScore = 0 (hard floor in IM docs).
  IsotonicRegression maps raw model outputs to historically correct
  frequencies, preventing over- or under-confidence.

Storage:
  Model artifacts saved to ~/.sparket/model_{league}.pkl (one per league).
  Loaded at startup; retrained every RETRAIN_EVERY_N resolved games.
"""
from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from sparket.miner.competitive.features import FEATURE_NAMES, N_FEATURES

# Minimum resolved games needed before trusting LightGBM over Elo
MIN_TRAIN_SAMPLES = 80

# Retrain after this many new resolved samples accumulate
RETRAIN_EVERY_N = 30

# LightGBM hyperparameters — tuned for small datasets on 16-core CPU
_LGB_PARAMS = {
    "objective": "binary",
    "metric": "binary_logloss",
    "n_estimators": 200,
    "learning_rate": 0.05,
    "num_leaves": 15,          # small tree — prevents overfit on small datasets
    "min_child_samples": 10,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.1,
    "reg_lambda": 0.1,
    "n_jobs": -1,               # uses all 16 cores
    "verbose": -1,
    "random_state": 42,
}

# VIG applied to convert probabilities to decimal odds
VIG = 0.045


class MatchPredictor:
    """Per-league prediction model with calibration.

    One instance per league. The service manages a dict of predictors.
    """

    def __init__(self, league: str, model_dir: str | Path = "~/.sparket/models") -> None:
        self.league = league.lower()
        self._dir = Path(os.path.expanduser(str(model_dir)))
        self._model_path = self._dir / f"model_{self.league}.pkl"

        self._lgb: Optional[object] = None        # LGBMClassifier
        self._cal: Optional[object] = None        # IsotonicRegression
        self._n_trained: int = 0
        self._n_since_retrain: int = 0
        self._training_rows: List[Dict] = []

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def load(self) -> bool:
        """Load saved model artifacts. Returns True if loaded."""
        if self._model_path.exists():
            try:
                with open(self._model_path, "rb") as f:
                    state = pickle.load(f)
                self._lgb = state.get("lgb")
                self._cal = state.get("cal")
                self._n_trained = state.get("n_trained", 0)
                self._training_rows = state.get("rows", [])
                return True
            except Exception:
                pass
        return False

    def save(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        with open(self._model_path, "wb") as f:
            pickle.dump({
                "lgb": self._lgb,
                "cal": self._cal,
                "n_trained": self._n_trained,
                "rows": self._training_rows[-5000:],  # keep last 5k to cap file size
            }, f)

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def add_resolved_row(self, features: np.ndarray, outcome: float) -> None:
        """Add a resolved game to training buffer.

        Args:
            features: Feature vector from features.build_feature_vector()
            outcome: 1.0 = home win, 0.0 = away win
        """
        self._training_rows.append({
            "X": features.tolist(),
            "y": outcome,
        })
        self._n_since_retrain += 1

        if (
            len(self._training_rows) >= MIN_TRAIN_SAMPLES
            and self._n_since_retrain >= RETRAIN_EVERY_N
        ):
            self.train()

    def train(self) -> bool:
        """Train or retrain LightGBM + calibration on buffered rows.

        Returns True if training succeeded.
        """
        rows = self._training_rows
        if len(rows) < MIN_TRAIN_SAMPLES:
            return False

        try:
            import lightgbm as lgb
            from sklearn.calibration import CalibratedClassifierCV
            from sklearn.isotonic import IsotonicRegression
            from sklearn.model_selection import train_test_split

            X = np.array([r["X"] for r in rows], dtype=np.float32)
            y = np.array([r["y"] for r in rows], dtype=np.float32)

            # Split for calibration
            X_train, X_cal, y_train, y_cal = train_test_split(
                X, y, test_size=0.2, random_state=42
            )

            # Train LightGBM
            clf = lgb.LGBMClassifier(**_LGB_PARAMS)
            clf.fit(X_train, y_train)

            # Calibrate on held-out set using isotonic regression
            raw_probs = clf.predict_proba(X_cal)[:, 1]
            iso = IsotonicRegression(out_of_bounds="clip")
            iso.fit(raw_probs, y_cal)

            self._lgb = clf
            self._cal = iso
            self._n_trained = len(rows)
            self._n_since_retrain = 0

            return True
        except ImportError:
            # lightgbm not installed — fall back to Elo
            return False
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def is_ready(self) -> bool:
        """True if LightGBM model is trained and calibrated."""
        return self._lgb is not None and self._cal is not None

    def predict_home_prob(self, features: np.ndarray) -> float:
        """Return calibrated P(home wins). Falls back gracefully."""
        if not self.is_ready():
            # Elo-based probability is at features[1] (p_elo_home)
            return float(np.clip(features[1], 0.05, 0.95))

        try:
            raw = self._lgb.predict_proba(features.reshape(1, -1))[0, 1]
            calibrated = float(self._cal.predict([raw])[0])
            return float(np.clip(calibrated, 0.05, 0.95))
        except Exception:
            return float(np.clip(features[1], 0.05, 0.95))

    def price_market(
        self,
        features: np.ndarray,
        kind: str,
        line: Optional[float] = None,
    ) -> Optional[Dict]:
        """Generate priced sides for a market.

        Returns dict with 'prices' list ready for submission payload,
        or None if pricing is not possible.

        Args:
            features: Feature vector from build_feature_vector()
            kind: 'moneyline' | 'spread' | 'total'
            line: Spread/total line value (unused for moneyline)
        """
        kind = kind.lower()
        p_home = self.predict_home_prob(features)
        p_away = 1.0 - p_home

        if kind == "moneyline":
            return {
                "prices": [
                    {
                        "side": "home",
                        "odds_eu": _prob_to_eu(p_home),
                        "imp_prob": round(p_home, 6),
                    },
                    {
                        "side": "away",
                        "odds_eu": _prob_to_eu(p_away),
                        "imp_prob": round(p_away, 6),
                    },
                ]
            }

        elif kind == "spread":
            # For spread, use slightly shaded probabilities around 50%
            # (spread line already accounts for team quality)
            # Shift based on model confidence: if home is strong, skew cover prob
            spread_home = _spread_prob(p_home)
            spread_away = 1.0 - spread_home
            return {
                "prices": [
                    {
                        "side": "home",
                        "odds_eu": _prob_to_eu(spread_home),
                        "imp_prob": round(spread_home, 6),
                    },
                    {
                        "side": "away",
                        "odds_eu": _prob_to_eu(spread_away),
                        "imp_prob": round(spread_away, 6),
                    },
                ]
            }

        elif kind == "total":
            # Total (over/under) is less correlated with ML — use 0.5 with slight
            # variance added from pts_diff features (features[7] and [8])
            pts_diff_home = float(features[7])   # normalized pts_diff_home
            pts_diff_away = float(features[8])   # normalized pts_diff_away
            # Both high-scoring teams → lean over
            combined_scoring = (pts_diff_home + pts_diff_away) / 2.0
            p_over = float(np.clip(0.5 + combined_scoring * 0.12, 0.35, 0.65))
            p_under = 1.0 - p_over
            return {
                "prices": [
                    {
                        "side": "over",
                        "odds_eu": _prob_to_eu(p_over),
                        "imp_prob": round(p_over, 6),
                    },
                    {
                        "side": "under",
                        "odds_eu": _prob_to_eu(p_under),
                        "imp_prob": round(p_under, 6),
                    },
                ]
            }

        return None


# ------------------------------------------------------------------
# Model registry — one predictor per league
# ------------------------------------------------------------------

class ModelRegistry:
    """Manages MatchPredictor instances per league."""

    def __init__(self, model_dir: str | Path = "~/.sparket/models") -> None:
        self._dir = model_dir
        self._predictors: Dict[str, MatchPredictor] = {}

    def get(self, league: str) -> MatchPredictor:
        league = league.lower()
        if league not in self._predictors:
            p = MatchPredictor(league, self._dir)
            p.load()
            self._predictors[league] = p
        return self._predictors[league]

    def save_all(self) -> None:
        for p in self._predictors.values():
            p.save()

    def add_resolved(
        self,
        league: str,
        features: np.ndarray,
        home_score: float,
        away_score: float,
    ) -> None:
        """Feed a resolved game into the correct league model."""
        if home_score == away_score:
            outcome = 0.5
        elif home_score > away_score:
            outcome = 1.0
        else:
            outcome = 0.0
        self.get(league).add_resolved_row(features, outcome)


# ------------------------------------------------------------------
# Utility
# ------------------------------------------------------------------

def _prob_to_eu(prob: float) -> float:
    """Convert true probability → EU decimal odds with vig."""
    p_with_vig = prob * (1.0 + VIG / 2.0)
    p_with_vig = max(0.01, min(0.99, p_with_vig))
    return round(1.0 / p_with_vig, 3)


def _spread_prob(p_ml_home: float) -> float:
    """Estimate P(home covers spread) from moneyline probability.

    A strong home favourite covers the spread more often than a coin flip,
    but less often than they win outright. Simplified linear mapping.
    """
    # Map: p=0.5 → spread_p=0.50, p=0.80 → spread_p=0.57, p=0.20 → spread_p=0.43
    return float(np.clip(0.50 + (p_ml_home - 0.50) * 0.30, 0.35, 0.65))
