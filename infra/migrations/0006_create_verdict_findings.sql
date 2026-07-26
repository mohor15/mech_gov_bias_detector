-- Join table: a GovernanceVerdict aggregates one or more Findings
-- (architecture §16.1's "contributing findings", plural). Exactly one row
-- per verdict today since GovernanceEngine only ever runs one Policy — M4
-- is what starts inserting more than one row per verdict, not this table.
CREATE TABLE verdict_findings (
    verdict_id  TEXT NOT NULL REFERENCES verdicts(id),
    finding_id  TEXT NOT NULL REFERENCES findings(id),
    PRIMARY KEY (verdict_id, finding_id)
);
