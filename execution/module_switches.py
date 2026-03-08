
"""
Module switches for SAFE / DEBUG mode.

True  = module enabled
False = module disabled

Goal:
Run the bot with minimal components to debug WS / strategy / execution.
"""

MODULES = {

    # ===============================
    # CORE (leave enabled)
    # ===============================

    "ws_stream": True,        # websocket market data
    "strategy": True,         # signal generation
    "orders": True,           # order execution


    # ===============================
    # OPTIONAL SYSTEM LAYERS
    # ===============================

    "guardian": False,        # system watchdog / monitoring
    "execution_brain": False, # advanced decision matrix
    "smart_router": False,    # order routing
    "trade_manager": False,   # advanced trade lifecycle
    "portfolio": False,       # exposure tracking


    # ===============================
    # ADVANCED FEATURES
    # ===============================

    "ml": False,              # machine learning signal filter
    "database": False,        # trade database logging
    "analytics": False,       # metrics / performance tracking


    # ===============================
    # RISK EXTENSIONS
    # ===============================

    "advanced_risk": False,   # advanced risk layers
    "partial_tp": False,      # partial take profit logic
    "trailing_stop": False,   # trailing stop system
}


def enabled(name: str) -> bool:
    """
    Check if module is enabled.

    Example:
        if enabled("guardian"):
            start_guardian()
    """
    return MODULES.get(name, False)
