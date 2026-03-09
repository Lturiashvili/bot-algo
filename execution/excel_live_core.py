import os
from dataclasses import dataclass
from typing import Dict, Any


# -------------------------------------------------
# INPUT STRUCTURE
# -------------------------------------------------

@dataclass
class CoreInputs:

    trend_strength: float
    structure_ok: bool
    volume_score: float
    risk_state: str
    confidence_score: float
    volatility_regime: str


# -------------------------------------------------
# AI CORE ENGINE
# -------------------------------------------------

class ExcelLiveCore:

    def __init__(self, model_path: str = None):

        # აღარ ვიყენებთ Excel-ს
        self.execute_threshold = 0.6


    # -------------------------------------------------
    # VOLATILITY REGIME MAPPING
    # -------------------------------------------------

    def _volatility_to_numeric(self, regime: str) -> int:

        mapping = {
            "LOW": 0,
            "MEDIUM": 1,
            "HIGH": 2
        }

        return mapping.get(regime.upper(), 1)


    # -------------------------------------------------
    # AI SCORE CALCULATION
    # -------------------------------------------------

    def _calculate_score(self, inputs: CoreInputs) -> float:

        # -----------------------------
        # CONF BASE
        # -----------------------------

        conf_base = (
            inputs.confidence_score * 0.4
            + inputs.volume_score * 0.3
            + inputs.trend_strength * 0.3
        )

        # -----------------------------
        # HEALTH
        # -----------------------------

        health = 1.0 if inputs.volume_score > 0.4 else 0.7

        # -----------------------------
        # RISK
        # -----------------------------

        risk = 1.0 if inputs.structure_ok else 0.6

        # -----------------------------
        # VOLATILITY REGIME
        # -----------------------------

        regime_num = self._volatility_to_numeric(inputs.volatility_regime)

        regime_adj = 1 + regime_num * 0.2

        # -----------------------------
        # FINAL SCORE
        # -----------------------------

        ai_score = conf_base * health * risk * regime_adj

        return round(ai_score, 4)


    # -------------------------------------------------
    # DECISION
    # -------------------------------------------------

    def decide(self, inputs: CoreInputs) -> Dict[str, Any]:

        ai_score = self._calculate_score(inputs)

        decision = "EXECUTE" if ai_score >= self.execute_threshold else "BLOCK"

        return {
            "ai_score": ai_score,
            "final_trade_decision": decision
        }
