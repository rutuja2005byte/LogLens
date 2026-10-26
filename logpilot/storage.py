"""SQLite-backed log store. Replaces Logstash + Elasticsearch (stdlib only)."""
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


class LogStore:
    def __init__(self, db_path: Path, json_log_path: Path | None = None):
        self.db_path = Path(db_path)
        self.json_log_path = Path(json_log_path) if json_log_path else None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    service TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    method TEXT,
                    url TEXT,
                    status_code INTEGER
                )"""
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level, timestamp)")

    def write(self, service, level, message, method=None, url=None, status_code=None) -> dict:
        event = {
            "@timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "service": service,
            "level": level,
            "message": message,
            "method": method,
            "url": url,
            "statusCode": status_code,
        }
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO logs (timestamp, service, level, message, method, url, status_code)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (event["@timestamp"], service, level, message, method, url, status_code),
            )
        line = json.dumps(event)
        if self.json_log_path:
            with self._lock, open(self.json_log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        print(line, flush=True)
        return event

    def stats(self) -> dict:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
            errors = self._conn.execute("SELECT COUNT(*) FROM logs WHERE level = 'ERROR'").fetchone()[0]
            rows = self._conn.execute(
                "SELECT status_code, COUNT(*) AS n FROM logs WHERE status_code IS NOT NULL"
                " GROUP BY status_code ORDER BY n DESC LIMIT 10"
            ).fetchall()
        return {
            "totalEvents": total,
            "errorEvents": errors,
            "statusCodes": {str(r["status_code"]): r["n"] for r in rows},
        }

    def recent_errors(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM logs WHERE level = 'ERROR' ORDER BY timestamp DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "@timestamp": r["timestamp"],
                "service": r["service"],
                "level": r["level"],
                "message": r["message"],
                "method": r["method"],
                "url": r["url"],
                "statusCode": r["status_code"],
            }
            for r in rows
        ]

    def close(self):
        with self._lock:
            self._conn.close()
