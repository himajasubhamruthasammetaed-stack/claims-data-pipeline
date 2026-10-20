import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from pipeline.generate import generate
from pipeline.load import build_marts, load_staging
from pipeline.quality import check_claims, reconcile


@pytest.fixture(scope="module")
def frames():
    members, claims, rx = generate(n_members=200, n_claims=1000, n_rx=500, seed=7)
    return {"members": members, "claims": claims, "pharmacy_claims": rx}


def test_quality_catches_every_injected_problem(frames):
    clean, bad, report = check_claims(frames["claims"], frames["members"])
    assert report.failures["null_member_id"] > 0
    assert report.failures["unknown_member"] > 0
    assert report.failures["negative_paid"] > 0
    assert report.failures["duplicate_claim_id"] > 0
    # nothing bad slips into the clean set
    assert clean["member_id"].isin(frames["members"]["member_id"]).all()
    assert (clean["paid_amount"] >= 0).all()
    assert clean["claim_id"].is_unique
    assert set(bad["reject_reason"]) <= set(report.failures)


def test_reconcile_raises_on_lost_rows():
    reconcile(100, 90, 10)
    with pytest.raises(ValueError):
        reconcile(100, 90, 5)


def test_end_to_end_load_and_marts(frames, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'claims.db'}")
    reports = load_staging(engine, frames)
    build_marts(engine)

    claims_report = next(r for r in reports if r["table"] == "claims")
    with engine.connect() as conn:
        staged = conn.execute(text("SELECT COUNT(*) FROM stg_claims")).scalar_one()
        quarantined = conn.execute(text("SELECT COUNT(*) FROM quarantine_claims")).scalar_one()
        plans = pd.read_sql("SELECT * FROM mart_plan_cost_summary", conn)

    assert staged + quarantined == claims_report["rows_in"]
    assert len(plans) > 0
    assert (plans["total_paid"] >= plans["medical_paid"]).all()
