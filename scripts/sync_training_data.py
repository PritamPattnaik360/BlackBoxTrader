"""
Export / import the bot's learning data so it can live in git.

The SQLite database (backend/blackbox.db) is git-ignored, so the data the bot
learns from is mirrored to plain JSONL files under data/training/:

    llm_training_sample.jsonl   instruction/response pairs for LLM fine-tuning
    signal_outcome.jsonl        BUY/SELL signal outcomes used by the adaptive engine
    day_trade.jsonl             day-trade journal (entry/exit/P&L/reason)

Usage:
    python scripts/sync_training_data.py export   # DB -> data/training/*.jsonl  (run by the git hooks)
    python scripts/sync_training_data.py import   # data/training/*.jsonl -> DB  (fresh clone / new machine)

Export is deterministic (sorted, stable keys) so unchanged data produces no git diff.
Import skips rows already present (matched by a content key), so it is safe to re-run.
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "backend" / "blackbox.db"
OUT_DIR = ROOT / "data" / "training"

# table -> columns that identify a row independent of its auto-increment id
TABLES = {
    "llm_training_sample": ("instruction", "response", "ticker", "created_at"),
    "signal_outcome": None,      # resolved below from the actual schema
    "day_trade": ("ticker", "entry_time", "entry_price"),
}


def _connect(readonly: bool) -> sqlite3.Connection:
    if readonly:
        return sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True, timeout=10)
    return sqlite3.connect(DB_PATH, timeout=10)


def _columns(conn, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _exists(conn, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def export_data() -> int:
    if not DB_PATH.exists():
        print(f"[training-data] no database at {DB_PATH} - nothing to export")
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect(readonly=True)
    total = 0
    try:
        for table in TABLES:
            if not _exists(conn, table):
                continue
            cols = [c for c in _columns(conn, table) if c != "id"]
            rows = conn.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
            lines = sorted(json.dumps(dict(zip(cols, r)), sort_keys=True, ensure_ascii=False, default=str) for r in rows)
            (OUT_DIR / f"{table}.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8", newline="\n")
            total += len(lines)
            print(f"[training-data] {table}: {len(lines)} rows")
    finally:
        conn.close()
    return total


def import_data() -> int:
    if not DB_PATH.exists():
        print(f"[training-data] {DB_PATH} not found - start the backend once to create it, then re-run")
        return 1
    conn = _connect(readonly=False)
    added = 0
    try:
        for table in TABLES:
            path = OUT_DIR / f"{table}.jsonl"
            if not path.exists() or not _exists(conn, table):
                continue
            cols = [c for c in _columns(conn, table) if c != "id"]
            key_cols = TABLES[table] or tuple(cols)
            existing = {tuple(str(r[i]) for i in range(len(key_cols)))
                        for r in conn.execute(f"SELECT {', '.join(key_cols)} FROM {table}")}
            n = 0
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                key = tuple(str(row.get(c)) for c in key_cols)
                if key in existing:
                    continue
                use = [c for c in cols if c in row]
                vals = [json.dumps(row[c]) if isinstance(row[c], (dict, list)) else row[c] for c in use]
                conn.execute(f"INSERT INTO {table} ({', '.join(use)}) VALUES ({', '.join('?' * len(use))})", vals)
                existing.add(key)
                n += 1
            added += n
            print(f"[training-data] {table}: imported {n} new rows")
        conn.commit()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "export"
    if cmd == "export":
        export_data()
    elif cmd == "import":
        sys.exit(import_data())
    else:
        sys.exit("usage: sync_training_data.py [export|import]")
