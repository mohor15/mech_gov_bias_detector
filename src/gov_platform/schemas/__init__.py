"""Canonical, domain-agnostic models shared across the platform.

These are the "seams" architecture §4.2 describes: every adapter translates
into a `DecisionEvent`, every policy produces a `Finding`, and the governance
engine produces a `GovernanceVerdict`. Nothing downstream of these models
should need to know which source system or policy produced them.
"""
