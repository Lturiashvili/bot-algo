from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite


@dataclass(frozen=True)
class TradeRow:
    id: int
    exchange: str
    symbol: str
    side: str
    qty: float
    entry_price: float
    exit_price: Optional[float]
    entry_time: str
    exit_time: Optional[str]
    pnl_usd: Optional[float]
    fee_usd: float
    meta_json: str


class TradeDB:
    """
    Production-safe SQLite wrapper for Render/K8s:
    - resolves DB path to persistent disk when available (/var/data)
    - ensures parent dir exists
    - performs a quick write-test
    - sets WAL + sane pragmas
    """

    def __init__(self, path: str) -> None:
        self.path = self._resolve_db_path(path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _resolve_db_path(raw: str) -> str:
        raw = (raw or "").strip()

        # Allow in-memory db explicitly
        if raw in (":memory:", "file::memory:"):
            return raw

        # If empty, pick a safe default
        if not raw:
            raw = "trades_v3.db"

        p = Path(raw)

        # If relative path, prefer Render persistent disk if present
        if not p.is_absolute():
            render_disk = Path("/var/data")
            if render_disk.exists() and render_disk.is_dir():
                p = render_disk / p.name  # keep filename, persist on disk
            else:
                # fallback to current working directory (may still be read-only)
                p = (Path.cwd() / p).resolve()

        # Ensure parent directory exists
        parent = p.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise RuntimeError(
                f"[DB] Cannot create parent directory for sqlite db.\n"
                f"db_path={str(p)}\nparent={str(parent)}\n"
                f"cwd={os.getcwd()}\nerr={repr(e)}"
            ) from e

        # Quick write permission test (create file if missing)
        try:
            # create file if not exists; won't truncate
            with open(p, "a", encoding="utf-8"):
                pass
        except Exception as e:
            # Provide a very actionable diagnostic
            try:
                parent_ls = sorted(os.listdir(parent))
            except Exception:
                parent_ls = ["<cannot list>"]

            raise RuntimeError(
                f"[DB] No write access to sqlite db path.\n"
                f"db_path={str(p)}\nparent={str(parent)}\n"
                f"cwd={os.getcwd()}\nparent_ls={parent_ls[:50]}\n"
                f"hint=Use Render Disk and set DB_PATH=/var/data/trades_v3.db\n"
                f"err={repr(e)}"
            ) from e

        return str(p)

    async def _connect(self) -> aiosqlite.Connection:
        """
        Centralized connection with pragmas.
        """
        try:
            db = await aiosqlite.connect(self.path, timeout=30)
        except Exception as e:
            raise RuntimeError(
                f"[DB] sqlite connect failed.\n"
                f"db_path={self.path}\n"
                f"cwd={os.getcwd()}\n"
                f"hint=Set DB_PATH=/var/data/trades_v3.db and ensure disk mounted to /var/data\n"
                f"err={repr(e)}"
            ) from e

        # Sane pragmas for a small trading journal
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        await db.execute("PRAGMA foreign_keys=ON;")
        await db.execute("PRAGMA busy_timeout=30000;")
        return db

    async def init(self) -> None:
        async with await self._connect() as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT,
                    pnl_usd REAL,
                    fee_usd REAL NOT NULL,
                    meta_json TEXT NOT NULL
                );
                """
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_trades_exchange ON trades(exchange);")
            await db.commit()

    async def insert_entry(
        self,
        exchange: str,
        symbol: str,
        qty: float,
        entry_price: float,
        fee_usd: float,
        meta: dict[str, Any],
    ) -> int:
        async with await self._connect() as db:
            cur = await db.execute(
                """
                INSERT INTO trades(
                    exchange, symbol, side, qty, entry_price,
                    exit_price, entry_time, exit_time, pnl_usd, fee_usd, meta_json
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?);
                """,
                (
                    exchange,
                    symbol,
                    "BUY",
                    qty,
                    entry_price,
                    None,
                    self._now(),
                    None,
                    None,
                    float(fee_usd),
                    json.dumps(meta, ensure_ascii=False),
                ),
            )
            await db.commit()
            return int(cur.lastrowid)

    async def close_trade(self, trade_id: int, exit_price: float, pnl_usd: float, fee_usd_add: float) -> None:
        async with await self._connect() as db:
            await db.execute(
                """
                UPDATE trades
                SET exit_price=?, exit_time=?, pnl_usd=?, fee_usd=fee_usd+?
                WHERE id=?;
                """,
                (float(exit_price), self._now(), float(pnl_usd), float(fee_usd_add), int(trade_id)),
            )
            await db.commit()
