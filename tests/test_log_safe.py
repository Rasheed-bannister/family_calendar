"""Tests for src/log_safe.py."""

import logging

from src.log_safe import log_safe


def test_escapes_line_breaks():
    assert log_safe("a\nb\rc") == "a\\nb\\rc"


def test_plain_values_are_unchanged():
    assert log_safe("Dishes") == "Dishes"
    assert log_safe(42) == "42"


def test_chore_text_cannot_forge_a_log_line(tmp_path, monkeypatch, caplog):
    from src.chores_app import database as chores_db

    monkeypatch.setattr(chores_db, "DATABASE_FILE", tmp_path / "chores.db")
    chores_db.create_all()
    with caplog.at_level(logging.INFO, logger=chores_db.logger.name):
        chores_db.add_chore(
            assigned_to="Kid",
            description="Dishes\n2026-01-01 - src.app - CRITICAL - forged",
        )
    added = [
        r.getMessage() for r in caplog.records if "added to local DB" in r.getMessage()
    ]
    assert len(added) == 1
    assert "\n" not in added[0]
    assert "\\n2026-01-01" in added[0]
