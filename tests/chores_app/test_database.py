"""Tests for src/chores_app/database.py."""

import sqlite3
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from src.chores_app import database as db
from src.chores_app.models import Chore


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary chores database."""
    db_path = tmp_path / "test_chores.db"
    with patch.object(db, "DATABASE_FILE", db_path):
        db.create_all()
        yield db_path


class _TrackedConnection:
    """Proxy around a real sqlite3 connection that records whether it was closed."""

    def __init__(self, wrapped):
        self._wrapped = wrapped
        self.closed = False

    def __getattr__(self, name):
        return getattr(self._wrapped, name)

    def close(self):
        self.closed = True
        self._wrapped.close()


@contextmanager
def track_connections():
    """Wrap sqlite3.connect so tests can assert no connection is leaked."""
    opened = []
    real_connect = sqlite3.connect

    def fake_connect(*args, **kwargs):
        conn = _TrackedConnection(real_connect(*args, **kwargs))
        opened.append(conn)
        return conn

    with patch("src.chores_app.database.sqlite3.connect", fake_connect):
        yield opened


def _break_schema(db_path):
    """Drop the Chores table so the next database operation raises mid-flight."""
    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE Chores")
    conn.commit()
    conn.close()


def _insert_raw_chore(db_path, chore_id, assigned_to, description, status, due=None):
    """Insert a row directly, bypassing add_chore's status normalisation."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO Chores (id, assigned_to, description, status, due) VALUES (?, ?, ?, ?, ?)",
        (chore_id, assigned_to, description, status, due),
    )
    conn.commit()
    conn.close()


class TestCreateAll:
    """Tests for chores database creation."""

    def test_creates_chores_table(self, tmp_path):
        db_path = tmp_path / "test.db"
        with patch.object(db, "DATABASE_FILE", db_path):
            db.create_all()
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            conn.close()
            assert "Chores" in tables

    def test_does_not_truncate_existing_database(self, temp_db):
        """create_all must be safe to call against a populated database."""
        with patch.object(db, "DATABASE_FILE", temp_db):
            db.add_chore(assigned_to="Alice", description="Dishes", google_id="keep-1")

            db.create_all()

            chores = db.get_chores()
            assert [c["id"] for c in chores] == ["keep-1"]


class TestAddChores:
    """Tests for add_chores (batch insert)."""

    def test_add_new_chores(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            chores = [
                Chore(
                    id="1",
                    title="Alice",
                    notes="Dishes",
                    status="needsAction",
                    due=None,
                ),
                Chore(
                    id="2", title="Bob", notes="Vacuum", status="completed", due=None
                ),
            ]
            db.add_chores(chores)
            result = db.get_chores()
            assert len(result) == 2

    def test_does_not_overwrite_invisible(self, temp_db):
        """Chores marked invisible should not be overwritten by Google sync."""
        with patch.object(db, "DATABASE_FILE", temp_db):
            # Add a chore and mark it invisible
            chore = Chore(
                id="1", title="Alice", notes="Dishes", status="invisible", due=None
            )
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO Chores (id, assigned_to, description, status, due) VALUES (?, ?, ?, ?, ?)",
                (
                    chore.id,
                    chore.assigned_to,
                    chore.description,
                    chore.status,
                    chore.due,
                ),
            )
            conn.commit()
            conn.close()

            # Try to update with Google data
            updated_chore = Chore(
                id="1", title="Alice", notes="Dishes", status="needsAction", due=None
            )
            db.add_chores([updated_chore])

            # Should still be invisible
            result = db.get_chores(include_invisible=True)
            invisible = [c for c in result if c["id"] == "1"]
            assert len(invisible) == 1
            assert invisible[0]["status"] == "invisible"

    def test_missing_status_is_defaulted(self, temp_db):
        """Google Tasks can omit `status`; it must not be persisted as NULL."""
        with patch.object(db, "DATABASE_FILE", temp_db):
            db.add_chores(
                [Chore(id="1", title="Alice", notes="Dishes", status=None, due=None)]
            )

            chores = db.get_chores()
            assert len(chores) == 1
            assert chores[0]["status"] == "needsAction"


class TestAddChore:
    """Tests for add_chore (single insert)."""

    def test_add_single_chore(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            result = db.add_chore(
                assigned_to="Alice",
                description="Do the laundry",
            )
            assert result is not None
            assert result.assigned_to == "Alice"
            assert result.description == "Do the laundry"
            assert result.status == "needsAction"

    def test_add_chore_with_google_id(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            result = db.add_chore(
                assigned_to="Bob",
                description="Vacuum",
                google_id="google-task-123",
            )
            assert result is not None
            assert result.id == "google-task-123"

    def test_add_chore_generates_uuid_without_google_id(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            result = db.add_chore(
                assigned_to="Carol",
                description="Mop",
            )
            assert result is not None
            assert len(result.id) == 36  # UUID format

    def test_add_duplicate_returns_none(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            db.add_chore(
                assigned_to="Alice",
                description="Task",
                google_id="dup-id",
            )
            result = db.add_chore(
                assigned_to="Bob",
                description="Other task",
                google_id="dup-id",
            )
            assert result is None


class TestUpdateChoreStatus:
    """Tests for update_chore_status."""

    def test_update_status(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            db.add_chore(assigned_to="Alice", description="Task", google_id="upd-1")
            db.update_chore_status("upd-1", "completed")
            chores = db.get_chores()
            matching = [c for c in chores if c["id"] == "upd-1"]
            assert len(matching) == 1
            assert matching[0]["status"] == "completed"


class TestGetChores:
    """Tests for get_chores."""

    def test_filters_invisible_by_default(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            db.add_chore(assigned_to="Alice", description="Visible", google_id="vis-1")
            db.add_chore(assigned_to="Bob", description="Hidden", google_id="hid-1")
            db.update_chore_status("hid-1", "invisible")

            visible = db.get_chores()
            assert len(visible) == 1
            assert visible[0]["id"] == "vis-1"

    def test_include_invisible(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            db.add_chore(assigned_to="Alice", description="Visible", google_id="vis-1")
            db.add_chore(assigned_to="Bob", description="Hidden", google_id="hid-1")
            db.update_chore_status("hid-1", "invisible")

            all_chores = db.get_chores(include_invisible=True)
            assert len(all_chores) == 2

    def test_returns_dict_format(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            db.add_chore(assigned_to="Alice", description="Dishes", google_id="fmt-1")
            chores = db.get_chores()
            assert len(chores) == 1
            chore = chores[0]
            assert "id" in chore
            assert "title" in chore  # assigned_to maps to title
            assert "notes" in chore  # description maps to notes
            assert "status" in chore
            assert "due" in chore

    def test_null_status_chore_is_returned(self, temp_db):
        """A NULL status is not 'invisible', so the chore must still show.

        `WHERE status != 'invisible'` alone drops these rows because
        `NULL != 'invisible'` evaluates to NULL rather than true.
        """
        with patch.object(db, "DATABASE_FILE", temp_db):
            _insert_raw_chore(temp_db, "null-1", "Alice", "Legacy chore", None)

            chores = db.get_chores()
            assert [c["id"] for c in chores] == ["null-1"]
            assert chores[0]["status"] is None

    def test_null_status_returned_but_invisible_still_filtered(self, temp_db):
        """Fixing the NULL case must not stop 'invisible' from being hidden."""
        with patch.object(db, "DATABASE_FILE", temp_db):
            _insert_raw_chore(temp_db, "null-1", "Alice", "Legacy chore", None)
            _insert_raw_chore(temp_db, "hid-1", "Bob", "Hidden chore", "invisible")
            db.add_chore(assigned_to="Carol", description="Normal", google_id="vis-1")

            visible_ids = {c["id"] for c in db.get_chores()}
            assert visible_ids == {"null-1", "vis-1"}

            all_ids = {c["id"] for c in db.get_chores(include_invisible=True)}
            assert all_ids == {"null-1", "hid-1", "vis-1"}


class TestConnectionHandling:
    """Connections must not leak when an operation raises mid-flight."""

    def test_get_chores_closes_connection_on_error(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            _break_schema(temp_db)

            with track_connections() as opened:
                with pytest.raises(sqlite3.Error):
                    db.get_chores()

            assert opened, "expected get_chores to open a connection"
            assert all(conn.closed for conn in opened)

    def test_update_chore_status_closes_connection_on_error(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            _break_schema(temp_db)

            with track_connections() as opened:
                with pytest.raises(sqlite3.Error):
                    db.update_chore_status("missing", "completed")

            assert opened, "expected update_chore_status to open a connection"
            assert all(conn.closed for conn in opened)

    def test_add_chores_closes_connection_on_error(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            _break_schema(temp_db)

            chores = [
                Chore(id="1", title="Alice", notes="Dishes", status=None, due=None)
            ]
            with track_connections() as opened:
                with pytest.raises(sqlite3.Error):
                    db.add_chores(chores)

            assert opened, "expected add_chores to open a connection"
            assert all(conn.closed for conn in opened)


class TestUpdateChoreGoogleId:
    """Tests for update_chore_google_id."""

    def test_updates_id(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            # Create a chore with local UUID
            local_chore = db.add_chore(assigned_to="Alice", description="Task")
            local_id = local_chore.id

            # Update to Google ID
            db.update_chore_google_id(local_id, "google-task-456")

            # Old ID should be gone, new ID should exist
            chores = db.get_chores()
            ids = [c["id"] for c in chores]
            assert "google-task-456" in ids
            assert local_id not in ids

    def test_same_id_no_op(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            db.add_chore(assigned_to="Alice", description="Task", google_id="same-id")
            # This should be a no-op
            db.update_chore_google_id("same-id", "same-id")
            chores = db.get_chores()
            assert len(chores) == 1
            assert chores[0]["id"] == "same-id"
