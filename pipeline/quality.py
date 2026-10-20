"""Data-quality checks for claims data.

Each check returns a boolean mask of BAD rows plus a reason, so bad rows can be
quarantined (kept for review) instead of silently dropped or silently loaded.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class QualityReport:
    table: str
    rows_in: int
    rows_passed: int = 0
    failures: dict[str, int] = field(default_factory=dict)

    @property
    def rows_quarantined(self) -> int:
        return self.rows_in - self.rows_passed

    def as_dict(self) -> dict:
        return {"table": self.table, "rows_in": self.rows_in, "rows_passed": self.rows_passed,
                "rows_quarantined": self.rows_quarantined, **{f"fail_{k}": v for k, v in self.failures.items()}}


def check_claims(claims: pd.DataFrame, members: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, QualityReport]:
    """Split claims into (clean, quarantined, report)."""
    report = QualityReport("claims", len(claims))
    reasons = pd.Series([""] * len(claims), index=claims.index, dtype=object)

    checks = {
        "null_member_id": claims["member_id"].isna(),
        "unknown_member": claims["member_id"].notna() & ~claims["member_id"].isin(members["member_id"]),
        "negative_paid": claims["paid_amount"] < 0,
        "paid_gt_billed": claims["paid_amount"] > claims["billed_amount"],
        "duplicate_claim_id": claims.duplicated("claim_id", keep="first"),
    }
    bad = pd.Series(False, index=claims.index)
    for name, mask in checks.items():
        report.failures[name] = int(mask.sum())
        reasons[mask & (reasons == "")] = name
        bad |= mask

    clean = claims[~bad].copy()
    quarantined = claims[bad].copy()
    quarantined["reject_reason"] = reasons[bad]
    report.rows_passed = len(clean)
    return clean, quarantined, report


def check_pharmacy(rx: pd.DataFrame, members: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, QualityReport]:
    report = QualityReport("pharmacy_claims", len(rx))
    checks = {
        "unknown_member": ~rx["member_id"].isin(members["member_id"]),
        "bad_days_supply": ~rx["days_supply"].isin([30, 60, 90]),
        "negative_paid": rx["paid_amount"] < 0,
        "duplicate_rx_id": rx.duplicated("rx_id", keep="first"),
    }
    bad = pd.Series(False, index=rx.index)
    reasons = pd.Series([""] * len(rx), index=rx.index, dtype=object)
    for name, mask in checks.items():
        report.failures[name] = int(mask.sum())
        reasons[mask & (reasons == "")] = name
        bad |= mask
    clean, quarantined = rx[~bad].copy(), rx[bad].copy()
    quarantined["reject_reason"] = reasons[bad]
    report.rows_passed = len(clean)
    return clean, quarantined, report


def reconcile(source_rows: int, loaded_rows: int, quarantined_rows: int) -> None:
    """Source-to-target reconciliation: every source row must be either loaded or quarantined."""
    if source_rows != loaded_rows + quarantined_rows:
        raise ValueError(f"reconciliation failed: source={source_rows} loaded={loaded_rows} "
                         f"quarantined={quarantined_rows}")
