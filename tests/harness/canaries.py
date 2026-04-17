"""Canary sentinels for secret-leak tests.

This module starts minimal in T06. Later waves extend it; they do not rename
the stable symbols introduced here.
"""
from __future__ import annotations


CANARY_SECRET: str = "CANARY-SMOKE-06-e3f8a2c1"
