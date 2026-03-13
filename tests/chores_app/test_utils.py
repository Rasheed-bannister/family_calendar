"""Tests for src/chores_app/utils.py."""

from unittest.mock import patch

from src.chores_app.models import Chore
from src.chores_app.utils import create_chores_from_google_data, make_chores_comparable


class TestMakeChoresComparable:
    """Tests for make_chores_comparable."""

    def test_empty_list(self):
        assert make_chores_comparable([]) == set()

    def test_none_returns_empty_set(self):
        assert make_chores_comparable(None) == set()

    def test_not_a_list(self):
        assert make_chores_comparable("not a list") is None

    def test_dict_items(self):
        chores = [
            {"id": "1", "title": "Alice", "notes": "Dishes", "status": "needsAction"},
            {"id": "2", "title": "Bob", "notes": "Vacuum", "status": "completed"},
        ]
        result = make_chores_comparable(chores)
        assert len(result) == 2
        assert ("1", "Alice", "Dishes", "needsAction") in result
        assert ("2", "Bob", "Vacuum", "completed") in result

    def test_chore_objects(self):
        chores = [
            Chore(
                id="1", title="Alice", notes="Dishes", status="needsAction", due=None
            ),
            Chore(id="2", title="Bob", notes="Vacuum", status="completed", due=None),
        ]
        result = make_chores_comparable(chores)
        assert len(result) == 2
        assert ("1", "Alice", "Dishes", "needsAction") in result

    def test_mixed_dict_and_objects(self):
        chores = [
            {"id": "1", "title": "Alice", "notes": "Dishes", "status": "needsAction"},
            Chore(id="2", title="Bob", notes="Vacuum", status="completed", due=None),
        ]
        result = make_chores_comparable(chores)
        assert len(result) == 2

    def test_duplicate_detection(self):
        """Two identical chores should produce same comparable set."""
        chores_a = [
            {"id": "1", "title": "Alice", "notes": "Dishes", "status": "needsAction"}
        ]
        chores_b = [
            {"id": "1", "title": "Alice", "notes": "Dishes", "status": "needsAction"}
        ]
        assert make_chores_comparable(chores_a) == make_chores_comparable(chores_b)

    def test_difference_detected(self):
        chores_a = [
            {"id": "1", "title": "Alice", "notes": "Dishes", "status": "needsAction"}
        ]
        chores_b = [
            {"id": "1", "title": "Alice", "notes": "Dishes", "status": "completed"}
        ]
        assert make_chores_comparable(chores_a) != make_chores_comparable(chores_b)


class TestCreateChoresFromGoogleData:
    """Tests for create_chores_from_google_data."""

    def test_empty_data(self):
        assert create_chores_from_google_data([]) == []
        assert create_chores_from_google_data(None) == []

    def test_basic_conversion(self):
        google_data = [
            {
                "id": "g-1",
                "title": "Alice",
                "notes": "Do the dishes",
                "status": "needsAction",
                "due": "2025-05-15T00:00:00Z",
            }
        ]
        chores = create_chores_from_google_data(google_data)
        assert len(chores) == 1
        assert chores[0].id == "g-1"
        assert chores[0].assigned_to == "Alice"
        assert chores[0].description == "Do the dishes"
        assert chores[0].status == "needsAction"

    def test_missing_title_defaults(self):
        google_data = [{"id": "g-2", "status": "needsAction"}]
        chores = create_chores_from_google_data(google_data)
        assert chores[0].assigned_to == "Unassigned"

    def test_missing_notes_defaults(self):
        google_data = [{"id": "g-3", "title": "Bob", "status": "completed"}]
        chores = create_chores_from_google_data(google_data)
        assert chores[0].description == ""

    def test_multiple_chores(self):
        google_data = [
            {"id": "g-1", "title": "Alice", "notes": "Task 1", "status": "needsAction"},
            {"id": "g-2", "title": "Bob", "notes": "Task 2", "status": "completed"},
        ]
        chores = create_chores_from_google_data(google_data)
        assert len(chores) == 2


class TestInitializeDb:
    """Tests for initialize_db."""

    @patch("src.chores_app.utils.db")
    def test_creates_if_not_exists(self, mock_db):
        mock_db.DATABASE_FILE.exists.return_value = False
        from src.chores_app.utils import initialize_db

        initialize_db()
        mock_db.create_all.assert_called_once()

    @patch("src.chores_app.utils.db")
    def test_does_nothing_if_exists(self, mock_db):
        mock_db.DATABASE_FILE.exists.return_value = True
        from src.chores_app.utils import initialize_db

        initialize_db()
        mock_db.create_all.assert_not_called()
