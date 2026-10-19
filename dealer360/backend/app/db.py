"""SQLite storage. Small, dependency-free; swap for Postgres when you scale."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  reg TEXT, vin TEXT, make TEXT, model TEXT, year INTEGER,
  length_mm INTEGER, width_mm INTEGER, notes TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vehicle_id INTEGER NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
  parent_id INTEGER REFERENCES shots(id) ON DELETE CASCADE,
  view TEXT, kind TEXT NOT NULL, source_camera TEXT,
  path TEXT NOT NULL, width INTEGER, height INTEGER, yaw REAL, quality TEXT,
  captured_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS defects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vehicle_id INTEGER NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
  shot_id INTEGER NOT NULL REFERENCES shots(id) ON DELETE CASCADE,
  label TEXT NOT NULL, score REAL, severity TEXT,
  panel_id TEXT, side TEXT, panel TEXT, band TEXT, description TEXT,
  box TEXT, zone TEXT, size_mm TEXT, mask TEXT,
  crop_path TEXT, overview_path TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  seen_in TEXT, detector TEXT, note TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shots_vehicle ON shots(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_defects_vehicle ON defects(vehicle_id);
"""

JSON_COLS = {"box", "zone", "size_mm", "seen_in", "mask", "quality"}

# columns added after the first release: (table, column, type)
MIGRATIONS = [("shots", "quality", "TEXT"), ("defects", "mask", "TEXT")]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as c:
            c.executescript(SCHEMA)
            for table, col, typ in MIGRATIONS:     # bring older databases up to date
                have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
                if col not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")

    def connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    # -- generic -----------------------------------------------------------------
    @staticmethod
    def _row(r: Optional[sqlite3.Row]) -> Optional[dict]:
        if r is None:
            return None
        d = dict(r)
        for k in JSON_COLS:
            if k in d and isinstance(d[k], str):
                try:
                    d[k] = json.loads(d[k])
                except json.JSONDecodeError:
                    pass
        return d

    def _insert(self, table: str, values: dict[str, Any]) -> int:
        vals = {k: (json.dumps(v) if k in JSON_COLS and v is not None else v) for k, v in values.items()}
        cols = ", ".join(vals)
        qs = ", ".join("?" for _ in vals)
        with self.connect() as c:
            cur = c.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", list(vals.values()))
            return int(cur.lastrowid)

    def _get(self, table: str, id_: int) -> Optional[dict]:
        with self.connect() as c:
            return self._row(c.execute(f"SELECT * FROM {table} WHERE id = ?", (id_,)).fetchone())

    def _list(self, sql: str, args: Iterable = ()) -> list[dict]:
        with self.connect() as c:
            return [self._row(r) for r in c.execute(sql, tuple(args)).fetchall()]

    # -- vehicles ----------------------------------------------------------------
    def add_vehicle(self, **v) -> int:
        v.setdefault("created_at", now())
        return self._insert("vehicles", v)

    def get_vehicle(self, vid: int) -> Optional[dict]:
        return self._get("vehicles", vid)

    def list_vehicles(self) -> list[dict]:
        rows = self._list("""
            SELECT v.*,
              (SELECT COUNT(*) FROM shots s WHERE s.vehicle_id = v.id AND s.kind != 'derived') AS shot_count,
              (SELECT COUNT(*) FROM defects d WHERE d.vehicle_id = v.id AND d.status != 'rejected') AS defect_count
            FROM vehicles v ORDER BY v.id DESC""")
        return rows

    def delete_vehicle(self, vid: int) -> None:
        with self.connect() as c:
            c.execute("DELETE FROM vehicles WHERE id = ?", (vid,))

    # -- shots -------------------------------------------------------------------
    def add_shot(self, **s) -> int:
        s.setdefault("captured_at", now())
        return self._insert("shots", s)

    def get_shot(self, sid: int) -> Optional[dict]:
        return self._get("shots", sid)

    def list_shots(self, vid: int) -> list[dict]:
        return self._list("SELECT * FROM shots WHERE vehicle_id = ? ORDER BY id", (vid,))

    def update_shot_path(self, sid: int, path: str) -> None:
        with self.connect() as c:
            c.execute("UPDATE shots SET path = ? WHERE id = ?", (path, sid))

    def update_shot_quality(self, sid: int, quality: dict) -> None:
        with self.connect() as c:
            c.execute("UPDATE shots SET quality = ? WHERE id = ?", (json.dumps(quality), sid))

    # -- defects -----------------------------------------------------------------
    def add_defect(self, **d) -> int:
        d.setdefault("created_at", now())
        return self._insert("defects", d)

    def get_defect(self, did: int) -> Optional[dict]:
        return self._get("defects", did)

    def list_defects(self, vid: int, include_rejected: bool = False) -> list[dict]:
        q = "SELECT * FROM defects WHERE vehicle_id = ?"
        if not include_rejected:
            q += " AND status != 'rejected'"
        return self._list(q + " ORDER BY id", (vid,))

    def update_defect(self, did: int, **fields) -> None:
        if not fields:
            return
        fields = {k: (json.dumps(v) if k in JSON_COLS and v is not None else v) for k, v in fields.items()}
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self.connect() as c:
            c.execute(f"UPDATE defects SET {sets} WHERE id = ?", [*fields.values(), did])
