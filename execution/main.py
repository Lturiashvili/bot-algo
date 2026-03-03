    async def maybe_open_position(self, symbol: str, idx: int) -> None:

        if self.portfolio.has_position(symbol):
            log.info(f"FILTER_DEBUG {symbol} BLOCKED: already_in_position")
            return

        if self.portfolio.in_cooldown(symbol, idx):
            log.info(f"FILTER_DEBUG {symbol} BLOCKED: cooldown_active")
            return

        df15 = self._df15[symbol]

        min_bars = max(self.s.EMA_SLOW + 5, 50)
        if len(df15) < min_bars:
            log.info(f"FILTER_DEBUG {symbol} BLOCKED: insufficient_bars len={len(df15)}")
            return

        df30 = df15
        df1h = df15

        sig = compute_long_signal(
            df15,
            df30,
            df1h,
            self.s.EMA_FAST,
            self.s.EMA_SLOW,
            self.s.RSI_PERIOD,
            self.s.RSI_LONG_MIN,
            self.s.ATR_PERIOD,
        )

        if sig is None:
            log.info(f"FILTER_DEBUG {symbol} BLOCKED: signal_none")
            return

        # ------------------------------------------
        # Detailed Filter Matrix Debug
        # ------------------------------------------

        ema_ok = getattr(sig, "ema_ok", None)
        rsi_ok = getattr(sig, "rsi_ok", None)
        atr_ok = getattr(sig, "atr_ok", None)
        action = getattr(sig, "action", None)
        confidence = getattr(sig, "confidence", None)

        if action != "BUY":
            log.info(
                f"FILTER_DEBUG {symbol} "
                f"action={action} "
                f"ema={ema_ok} "
                f"rsi={rsi_ok} "
                f"atr={atr_ok} "
                f"confidence={confidence}"
            )
            return

        if self.s.ML_ENABLED and not self.ml.allow(sig.features):
            log.info(f"FILTER_DEBUG {symbol} BLOCKED: ml_reject")
            return

        override = self.override.read_override()

        if override.enabled:

            if override.disable_new_entries:
                log.info(f"FILTER_DEBUG {symbol} BLOCKED: env_disable_new_entries")
                return

            if override.min_confidence_override:
                if hasattr(sig, "confidence"):
                    if sig.confidence < override.min_confidence_override:
                        log.info(f"FILTER_DEBUG {symbol} BLOCKED: env_confidence_reject")
                        return

        # ------------------------------------------
        # BUY CONFIRMED
        # ------------------------------------------

        log.info(
            f"BUY_SIGNAL_CONFIRMED {symbol} "
            f"ema={ema_ok} rsi={rsi_ok} atr={atr_ok} confidence={confidence}"
        )

        try:
            test_quote_usdt = 10.0

            log.info(f"EXECUTION_START {symbol} size={test_quote_usdt}USDT")

            order = await self.router.open_long(
                self.ex,
                symbol,
                test_quote_usdt
            )

            log.info(
                f"EXECUTION_DONE {symbol} "
                f"order_id={getattr(order, 'order_id', None)} "
                f"qty={getattr(order, 'executed_qty', None)} "
                f"avg_price={getattr(order, 'avg_price', None)} "
                f"status={getattr(order, 'status', None)}"
            )

        except Exception as e:
            log.exception(f"EXECUTION_FAILED {symbol} err={e}")
