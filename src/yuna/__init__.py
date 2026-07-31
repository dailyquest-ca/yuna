"""Yuna — Zak's trading research and automation operation.

The plan in docs/yuna_plan.md is law. Every rule the code enforces is registered
against the plan clause it comes from (see yuna.rules); tests/test_conformance.py
checks that mapping in both directions, so neither an unregistered rule nor an
unimplemented clause can go unnoticed.
"""
