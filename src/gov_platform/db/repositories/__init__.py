"""Repository layer — one class per entity, decoupling `EvidenceStore` and
the Admin API from SQL/ORM details (architecture §16, M1 Components list).

Every method takes an externally-supplied `Session` rather than opening its
own: `EvidenceStore.append` writes across six tables in one atomic
transaction, which requires a single shared session across every repository
call in that sequence, not five independent ones.
"""
