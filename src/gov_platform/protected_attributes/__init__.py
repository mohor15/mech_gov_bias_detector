"""Protected Attribute Resolution — architecture §4.3.

Classifies a Decision Event's protected attributes as direct, proxied, or
withheld, per a domain's static classification ruleset. Deliberately a
separate pipeline stage from `normalization` — see `resolver.py`'s module
docstring for why.
"""
