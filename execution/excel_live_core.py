
import os
from dataclasses import dataclass
from typing import Dict, Any

import pandas as pd


# -------------------------------------------------
# INPUT STRUCTURE (used by signal_generator)
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
# EXCEL AI CORE
# -------------------------------------------------

class ExcelLiveCore:

    def __init__(self, excel_path: str):

        if not os.path.exists(excel_path):
            raise FileNotFoundError(excel_path)

        self.excel_path = excel_path
        self.weights = self._load_weights()

        # execution threshold
        self.execute_threshold = 0.6


    # -------------------------------------------------
    # LOAD WEIGHTS FROM EXCEL
    # -------------------------------------------------

    def _load_weights(self) -> Dict[str, float]:

        df = pd.read_excel(
            self.excel_path,
            sheet_name="WEIGHT_THRESHOLD_MATRIX"
        )

        weights = {}

        for _, row in df.iterrows():

            comp = str(row["component"]).lower()
            weight = float(row["weight"])

            weights[comp] = weight

        return weights


    # -------------------------------------------------
    # SCORE CALCULATION
    # -------------------------------------------------

    def _calc_score(self, inputs: CoreInputs) -> float:

        score = 0.0

        score += self.weights.get("trend strength", 0) * inputs.trend_strength

        score += self.weights.get(
            "structure validation",
            0
        ) * (1 if inputs.structure_ok else 0)

        score += self.weights.get(
            "volume confirmation",
            0
        ) * inputs.volume_score

        score += self.weights.get(
            "confidence score",
            0
        ) * inputs.confidence_score

        # risk modifier
        risk_val = 1 if inputs.risk_state == "OK" else 0

        score += self.weights.get(
            "risk state modifier",
            0
        ) * risk_val

        return round(score, 4)


    # -------------------------------------------------
    # MAIN DECISION FUNCTION
    # -------------------------------------------------

    def decide(self, inputs: CoreInputs) -> Dict[str, Any]:

        ai_score = self._calc_score(inputs)

        decision = "EXECUTE" if ai_score >= self.execute_threshold else "BLOCK"

        return {
            "ai_score": ai_score,
            "final_trade_decision": decision
        }
