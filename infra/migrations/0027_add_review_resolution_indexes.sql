-- Supports "which reviews were resolved within a given window" (M12,
-- architecture §14) -- neither review table has an index shaped for this
-- today (migrations 0023/0024 index status alone, for the Admin API's
-- own status-filtered list endpoint). status leads the composite here,
-- unlike M7's own created_at-leading indexes (0017-0019): M7's queries
-- have no separate equality filter (status there is a GROUP BY output,
-- not a WHERE clause), while this query's WHERE clause always starts
-- with the highly selective `status = 'RESOLVED'` before ranging over
-- resolved_at -- the textbook-correct column order for an
-- equality-then-range composite index, named explicitly here so the
-- deliberate difference from M7's own convention doesn't read as an
-- inconsistency.
CREATE INDEX idx_verdict_reviews_status_resolved_at
    ON verdict_reviews (status, resolved_at);
CREATE INDEX idx_population_finding_reviews_status_resolved_at
    ON population_finding_reviews (status, resolved_at);
