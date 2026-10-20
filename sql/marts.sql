-- Reporting tables built from the clean staging tables.
-- Plain ANSI SQL so it runs on both PostgreSQL (docker) and SQLite (tests).

DROP TABLE IF EXISTS mart_member_monthly_cost;
CREATE TABLE mart_member_monthly_cost AS
SELECT
    m.member_id,
    m.plan,
    m.state,
    SUBSTR(c.service_date, 1, 7)          AS service_month,
    COUNT(*)                              AS claim_count,
    ROUND(SUM(c.paid_amount), 2)          AS medical_paid
FROM stg_claims c
JOIN stg_members m ON m.member_id = c.member_id
GROUP BY m.member_id, m.plan, m.state, SUBSTR(c.service_date, 1, 7);

DROP TABLE IF EXISTS mart_plan_cost_summary;
CREATE TABLE mart_plan_cost_summary AS
SELECT
    m.plan,
    COUNT(DISTINCT m.member_id)                                   AS members,
    ROUND(COALESCE(SUM(med.medical_paid), 0), 2)                  AS medical_paid,
    ROUND(COALESCE(SUM(rx.pharmacy_paid), 0), 2)                  AS pharmacy_paid,
    ROUND(COALESCE(SUM(med.medical_paid), 0)
        + COALESCE(SUM(rx.pharmacy_paid), 0), 2)                  AS total_paid
FROM stg_members m
LEFT JOIN (SELECT member_id, SUM(paid_amount) AS medical_paid FROM stg_claims GROUP BY member_id) med
       ON med.member_id = m.member_id
LEFT JOIN (SELECT member_id, SUM(paid_amount) AS pharmacy_paid FROM stg_pharmacy_claims GROUP BY member_id) rx
       ON rx.member_id = m.member_id
GROUP BY m.plan;

DROP TABLE IF EXISTS mart_top_drugs;
CREATE TABLE mart_top_drugs AS
SELECT
    drug_name,
    COUNT(*)                     AS fills,
    ROUND(SUM(paid_amount), 2)   AS pharmacy_paid
FROM stg_pharmacy_claims
GROUP BY drug_name;
