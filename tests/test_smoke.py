"""Smoke tests — just verify imports and basic config wiring."""
from __future__ import annotations


def test_config_loads():
    from app.config import settings
    assert settings.om_host.startswith("http")


def test_engines_import():
    from app.engines import analysis, cleaning, stewardship  # noqa: F401


def test_composite_math():
    from app.engines.cleaning import composite_quality
    assert composite_quality(100, 100, 100, 5.0) == 100.0
    assert composite_quality(0, 0, 0, 0) == 0.0
