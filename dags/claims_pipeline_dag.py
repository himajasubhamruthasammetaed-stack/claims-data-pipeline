"""Airflow DAG: generate -> load + quality check -> build marts, daily.

Retries, an SLA and a failure callback are set so a failed run is retried
automatically and anyone on call is told when it still fails.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

RAW_DIR = "/opt/airflow/project/data/raw"


def _alert_on_failure(context):
    ti = context["task_instance"]
    logging.error("ALERT: task %s in DAG %s failed (try %s). Log: %s",
                  ti.task_id, ti.dag_id, ti.try_number, ti.log_url)


def _generate():
    from pipeline.generate import generate
    from pathlib import Path
    out = Path(RAW_DIR)
    out.mkdir(parents=True, exist_ok=True)
    members, claims, rx = generate()
    members.to_csv(out / "members.csv", index=False)
    claims.to_csv(out / "claims.csv", index=False)
    rx.to_csv(out / "pharmacy_claims.csv", index=False)


def _load_and_check():
    from pipeline.load import get_engine, extract, load_staging
    from pathlib import Path
    reports = load_staging(get_engine(), extract(Path(RAW_DIR)))
    for r in reports:
        logging.info("quality report: %s", r)
        if r["rows_in"] and r["rows_quarantined"] / r["rows_in"] > 0.10:
            raise ValueError(f"{r['table']}: more than 10% of rows failed quality checks")


def _build_marts():
    from pipeline.load import get_engine, build_marts
    build_marts(get_engine())


default_args = {
    "owner": "data-engineering",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "on_failure_callback": _alert_on_failure,
    "sla": timedelta(hours=1),
}

with DAG(
    dag_id="claims_pipeline",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    default_args=default_args,
    tags=["healthcare", "claims"],
) as dag:
    generate_raw = PythonOperator(task_id="generate_raw_files", python_callable=_generate)
    load_check = PythonOperator(task_id="load_and_quality_check", python_callable=_load_and_check)
    marts = PythonOperator(task_id="build_reporting_marts", python_callable=_build_marts)

    generate_raw >> load_check >> marts
