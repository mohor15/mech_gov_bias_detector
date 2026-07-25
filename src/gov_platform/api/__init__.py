"""HTTP API surface.

M0 ships two routers: health and ingestion. The Advisory, Admin/Config,
Query/Reporting, and Webhook APIs from architecture §15 all depend on
concepts (bindings, policy plurality, reporting, review cases) that do not
exist until later milestones — they are not stubbed here, they simply do
not exist yet.
"""
