"""Generate synthetic (fake) healthcare data: members, medical claims and pharmacy claims.

No real patient data is used. A small share of rows is made deliberately "dirty"
(missing IDs, duplicates, unknown members, negative amounts) so the data-quality
step has something real to catch.
"""
from __future__ import annotations

import argparse
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

PLANS = ["HMO", "PPO", "EPO", "Medicare Advantage", "Medicaid"]
STATES = ["IL", "TX", "FL", "OH", "PA", "NY", "AZ", "GA"]
CLAIM_TYPES = ["inpatient", "outpatient", "professional", "emergency"]
DRUGS = [("atorvastatin", 18.5), ("metformin", 9.2), ("lisinopril", 7.4),
         ("insulin glargine", 285.0), ("albuterol", 42.0), ("adalimumab", 3150.0)]


def _random_date(rng: random.Random, start: date, days: int) -> date:
    return start + timedelta(days=rng.randrange(days))


def generate(n_members: int = 500, n_claims: int = 5000, n_rx: int = 3000,
             dirty_rate: float = 0.02, seed: int = 42):
    rng = random.Random(seed)
    start = date(2025, 1, 1)

    members = pd.DataFrame({
        "member_id": [f"M{i:06d}" for i in range(1, n_members + 1)],
        "plan": [rng.choice(PLANS) for _ in range(n_members)],
        "state": [rng.choice(STATES) for _ in range(n_members)],
        "birth_year": [rng.randint(1940, 2006) for _ in range(n_members)],
        "eligible_from": [_random_date(rng, date(2024, 1, 1), 365).isoformat()
                          for _ in range(n_members)],
    })

    member_ids = members["member_id"].tolist()
    claims = pd.DataFrame({
        "claim_id": [f"C{i:08d}" for i in range(1, n_claims + 1)],
        "member_id": [rng.choice(member_ids) for _ in range(n_claims)],
        "provider_id": [f"P{rng.randint(1, 120):04d}" for _ in range(n_claims)],
        "claim_type": [rng.choice(CLAIM_TYPES) for _ in range(n_claims)],
        "service_date": [_random_date(rng, start, 365).isoformat() for _ in range(n_claims)],
        "billed_amount": [round(rng.uniform(50, 25000), 2) for _ in range(n_claims)],
    })
    claims["paid_amount"] = (claims["billed_amount"] * [rng.uniform(0.2, 0.9) for _ in range(n_claims)]).round(2)

    rx = pd.DataFrame({
        "rx_id": [f"R{i:08d}" for i in range(1, n_rx + 1)],
        "member_id": [rng.choice(member_ids) for _ in range(n_rx)],
        "fill_date": [_random_date(rng, start, 365).isoformat() for _ in range(n_rx)],
    })
    picks = [rng.choice(DRUGS) for _ in range(n_rx)]
    rx["drug_name"] = [d for d, _ in picks]
    rx["days_supply"] = [rng.choice([30, 60, 90]) for _ in range(n_rx)]
    rx["paid_amount"] = [round(price * s / 30, 2) for (_, price), s in zip(picks, rx["days_supply"])]

    # --- inject dirty rows so the quality checks have real work to do ---
    n_dirty = max(1, int(n_claims * dirty_rate))
    dirty_idx = rng.sample(range(n_claims), n_dirty * 3)
    claims.loc[dirty_idx[:n_dirty], "member_id"] = None                       # missing member
    claims.loc[dirty_idx[n_dirty:2 * n_dirty], "member_id"] = "M999999"       # unknown member
    claims.loc[dirty_idx[2 * n_dirty:], "paid_amount"] = -1.0                 # impossible amount
    claims = pd.concat([claims, claims.sample(n_dirty, random_state=seed)])  # duplicate claims

    return members, claims.reset_index(drop=True), rx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/raw")
    parser.add_argument("--members", type=int, default=500)
    parser.add_argument("--claims", type=int, default=5000)
    parser.add_argument("--rx", type=int, default=3000)
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    members, claims, rx = generate(args.members, args.claims, args.rx)
    members.to_csv(out / "members.csv", index=False)
    claims.to_csv(out / "claims.csv", index=False)
    rx.to_csv(out / "pharmacy_claims.csv", index=False)
    print(f"wrote {len(members)} members, {len(claims)} claims, {len(rx)} pharmacy claims to {out}")


if __name__ == "__main__":
    main()
