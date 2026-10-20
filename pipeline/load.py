"""Extract -> quality check -> load -> build marts -> reconcile.

Runs against any SQLAlchemy database URL:
  * PostgreSQL in docker-compose:  postgresql+psycopg2://claims:claims@localhost:5432/claims
  * SQLite for local runs/tests:   sqlite:///claims.db  (default)
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from pipeline.quality import check_claims, check_pharmacy, reconcile

log = logging.getLogger("claims_pipeline")
ROOT = Path(__file__).resolve().parent.parent


def get_engine(url: str | None = None) -> Engine:
    return create_engine(url or os.getenv("CLAIMS_DB_URL", "sqlite:///claims.db"))


def extract(raw_dir: Path) -> dict[str, pd.DataFrame]:
    return {
        "members": pd.read_csv(raw_dir / "members.csv"),
        "claims": pd.read_csv(raw_dir / "claims.csv"),
        "pharmacy_claims": pd.read_csv(raw_dir / "pharmacy_claims.csv"),
    }


def load_staging(engine: Engine, frames: dict[str, pd.DataFrame]) -> list[dict]:
    members = frames["members"].drop_duplicates("member_id")
    claims_ok, claims_bad, claims_rep = check_claims(frames["claims"], members)
    rx_ok, rx_bad, rx_rep = check_pharmacy(frames["pharmacy_claims"], members)

    reconcile(claims_rep.rows_in, len(claims_ok), len(claims_bad))
    reconcile(rx_rep.rows_in, len(rx_ok), len(rx_bad))

    with engine.begin() as conn:
        members.to_sql("stg_members", conn, if_exists="replace", index=False)
        claims_ok.to_sql("stg_claims", conn, if_exists="replace", index=False)
        rx_ok.to_sql("stg_pharmacy_claims", conn, if_exists="replace", index=False)
        claims_bad.to_sql("quarantine_claims", conn, if_exists="replace", index=False)
        rx_bad.to_sql("quarantine_pharmacy_claims", conn, if_exists="replace", index=False)

    # target-side reconciliation: what landed in the database must match what we sent
    with engine.connect() as conn:
        for table, expected in [("stg_claims", len(claims_ok)), ("stg_pharmacy_claims", len(rx_ok))]:
            got = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            if got != expected:
                raise ValueError(f"{table}: expected {expected} rows in database, found {got}")

    return [claims_rep.as_dict(), rx_rep.as_dict()]


def build_marts(engine: Engine, sql_file: Path = ROOT / "sql" / "marts.sql") -> None:
    statements = [s.strip() for s in sql_file.read_text().split(";") if s.strip()]
    with engine.begin() as conn:
        for stmt in statements:
            # strip comment-only lines so SQLite and Postgres both accept the statement
            body = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--"))
            if body.strip():
                conn.execute(text(body))


def run(raw_dir: str | Path = "data/raw", db_url: str | None = None) -> dict:
    started = time.time()
    engine = get_engine(db_url)
    frames = extract(Path(raw_dir))
    reports = load_staging(engine, frames)
    build_marts(engine)
    summary = {"quality": reports, "seconds": round(time.time() - started, 2)}
    log.info("pipeline finished: %s", json.dumps(summary))
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(run(), indent=2))
