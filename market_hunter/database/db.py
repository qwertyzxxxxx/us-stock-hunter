import json
import sqlite3
import logging
from market_hunter.config import DB_PATH

logger = logging.getLogger(__name__)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables, unique indexes, and run column migrations."""
    conn = get_conn()
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS scan_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_date TEXT NOT NULL,
        market TEXT NOT NULL DEFAULT 'US',
        total_scanned INTEGER,
        valid_price_count INTEGER,
        rejected_bad_price_count INTEGER,
        total_signals INTEGER,
        duration_seconds REAL,
        status TEXT DEFAULT 'completed',
        error TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_run_id INTEGER REFERENCES scan_runs(id),
        symbol TEXT NOT NULL,
        company_name TEXT,
        sector TEXT,
        industry TEXT,
        market_cap REAL,
        signal_date TEXT NOT NULL,
        close_price REAL,
        volume REAL,
        trend_score REAL,
        relative_strength_score REAL,
        volume_score REAL,
        pullback_risk_score REAL,
        sector_score REAL,
        total_score REAL,
        strategies TEXT,
        diagnostics TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS strategy_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id INTEGER REFERENCES signals(id),
        strategy_name TEXT NOT NULL,
        symbol TEXT NOT NULL,
        signal_date TEXT NOT NULL,
        rank_in_strategy INTEGER,
        details TEXT,
        reason TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS evaluations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id INTEGER REFERENCES signals(id),
        symbol TEXT NOT NULL,
        signal_date TEXT NOT NULL,
        signal_price REAL,
        eval_date_5d TEXT,
        return_5d REAL,
        eval_date_10d TEXT,
        return_10d REAL,
        eval_date_20d TEXT,
        return_20d REAL,
        max_drawdown REAL,
        max_gain REAL,
        evaluated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()

    # Unique indexes
    for ddl in [
        """CREATE UNIQUE INDEX IF NOT EXISTS ux_signals_symbol_date
           ON signals(symbol, signal_date)""",
        """CREATE UNIQUE INDEX IF NOT EXISTS ux_strategy_results_symbol_strategy_date
           ON strategy_results(symbol, strategy_name, signal_date)""",
    ]:
        try:
            cur.execute(ddl)
            conn.commit()
        except sqlite3.OperationalError as e:
            logger.warning(f"Could not create unique index: {e}")

    # Column migrations — add columns that may be missing from older DB schemas
    _migrate_add_column(cur, conn, "signals", "diagnostics", "TEXT")
    _migrate_add_column(cur, conn, "strategy_results", "reason", "TEXT")
    _migrate_add_column(cur, conn, "scan_runs", "valid_price_count", "INTEGER")
    _migrate_add_column(cur, conn, "scan_runs", "rejected_bad_price_count", "INTEGER")

    conn.close()
    logger.info("Database initialized")


def _migrate_add_column(cur, conn, table: str, column: str, col_type: str):
    """Safely add a column to a table if it doesn't already exist."""
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        conn.commit()
        logger.debug(f"Migration: added {table}.{column}")
    except sqlite3.OperationalError:
        pass  # Column already exists


def insert_scan_run(run_date: str, total_scanned: int, total_signals: int,
                    duration: float, status: str = "completed", error: str = None,
                    valid_price_count: int = 0,
                    rejected_bad_price_count: int = 0) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO scan_runs
           (run_date, market, total_scanned, valid_price_count, rejected_bad_price_count,
            total_signals, duration_seconds, status, error)
           VALUES (?, 'US', ?, ?, ?, ?, ?, ?, ?)""",
        (run_date, total_scanned, valid_price_count, rejected_bad_price_count,
         total_signals, duration, status, error)
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


def upsert_signal(scan_run_id: int, signal: dict) -> int:
    """
    Insert a signal row for (symbol, signal_date).
    If the row already exists (same-day rerun), skip the insert and return
    the existing row's id.
    """
    conn = get_conn()
    cur = conn.cursor()

    diagnostics_json = None
    if signal.get("diagnostics"):
        try:
            diagnostics_json = json.dumps(signal["diagnostics"])
        except Exception:
            pass

    cur.execute(
        """INSERT OR IGNORE INTO signals
           (scan_run_id, symbol, company_name, sector, industry, market_cap, signal_date,
            close_price, volume, trend_score, relative_strength_score, volume_score,
            pullback_risk_score, sector_score, total_score, strategies, diagnostics)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            scan_run_id,
            signal.get("symbol"),
            signal.get("company_name"),
            signal.get("sector"),
            signal.get("industry"),
            signal.get("market_cap"),
            signal.get("signal_date"),
            signal.get("close_price"),
            signal.get("volume"),
            signal.get("trend_score"),
            signal.get("relative_strength_score"),
            signal.get("volume_score"),
            signal.get("pullback_risk_score"),
            signal.get("sector_score"),
            signal.get("total_score"),
            ",".join(signal.get("strategies", [])),
            diagnostics_json,
        )
    )
    conn.commit()

    if cur.lastrowid:
        signal_id = cur.lastrowid
    else:
        cur.execute(
            "SELECT id FROM signals WHERE symbol=? AND signal_date=?",
            (signal.get("symbol"), signal.get("signal_date")),
        )
        row = cur.fetchone()
        signal_id = row["id"] if row else 0
        logger.debug(
            f"Signal already exists for {signal.get('symbol')} on "
            f"{signal.get('signal_date')} — skipped insert, using id={signal_id}"
        )

    conn.close()
    return signal_id


def insert_strategy_result(signal_id: int, strategy_name: str, symbol: str,
                            signal_date: str, rank: int, details: str = "",
                            reason: str = ""):
    """
    Insert a strategy_result row. Silently skipped if the same
    (symbol, strategy_name, signal_date) already exists.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT OR IGNORE INTO strategy_results
           (signal_id, strategy_name, symbol, signal_date, rank_in_strategy, details, reason)
           VALUES (?,?,?,?,?,?,?)""",
        (signal_id, strategy_name, symbol, signal_date, rank, details, reason)
    )
    if cur.rowcount == 0:
        logger.debug(
            f"strategy_result already exists for {symbol}/{strategy_name} "
            f"on {signal_date} — skipped"
        )
    conn.commit()
    conn.close()


def get_unevaluated_signals(days_old_min: int = 5) -> list[dict]:
    """Get signals that haven't been evaluated yet and are old enough."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """SELECT s.id, s.symbol, s.signal_date, s.close_price
           FROM signals s
           LEFT JOIN evaluations e ON e.signal_id = s.id
           WHERE e.id IS NULL
             AND julianday('now') - julianday(s.signal_date) >= ?
           ORDER BY s.signal_date ASC""",
        (days_old_min,)
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def insert_evaluation(signal_id: int, eval_data: dict):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO evaluations
           (signal_id, symbol, signal_date, signal_price,
            eval_date_5d, return_5d, eval_date_10d, return_10d,
            eval_date_20d, return_20d, max_drawdown, max_gain)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            signal_id,
            eval_data.get("symbol"),
            eval_data.get("signal_date"),
            eval_data.get("signal_price"),
            eval_data.get("eval_date_5d"),
            eval_data.get("return_5d"),
            eval_data.get("eval_date_10d"),
            eval_data.get("return_10d"),
            eval_data.get("eval_date_20d"),
            eval_data.get("return_20d"),
            eval_data.get("max_drawdown"),
            eval_data.get("max_gain"),
        )
    )
    conn.commit()
    conn.close()


def get_recent_signals(limit: int = 100) -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """SELECT s.*, e.return_5d, e.return_10d, e.return_20d, e.max_drawdown, e.max_gain
           FROM signals s
           LEFT JOIN evaluations e ON e.signal_id = s.id
           ORDER BY s.signal_date DESC, s.total_score DESC
           LIMIT ?""",
        (limit,)
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_scan_runs(limit: int = 20) -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM scan_runs ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows
