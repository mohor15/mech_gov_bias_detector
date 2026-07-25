"""Audit & Evidence Store — architecture §13.

M0 ships a real, hash-chained, SQLite-backed ledger — not a stub. What it
does *not* yet have: database-privilege-enforced immutability (needs
Postgres, M1), retention tiers and legal-hold, and privilege classification
(both M11). See `evidence_store.EvidenceStore` for the precise boundary.
"""
