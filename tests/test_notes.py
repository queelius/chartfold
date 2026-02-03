"""Tests for personal notes CRUD in chartfold.db."""

import pytest

from chartfold.db import ChartfoldDB


@pytest.fixture
def notes_db(tmp_path):
    """Empty database with schema initialized for notes testing."""
    db_path = str(tmp_path / "notes_test.db")
    db = ChartfoldDB(db_path)
    db.init_schema()
    yield db
    db.close()


class TestSaveNote:
    def test_create_returns_id(self, notes_db):
        note_id = notes_db.save_note(title="Test Note", content="Some content")
        assert isinstance(note_id, int)
        assert note_id > 0

    def test_content_stored(self, notes_db):
        note_id = notes_db.save_note(title="My Title", content="My Content")
        note = notes_db.get_note(note_id)
        assert note["title"] == "My Title"
        assert note["content"] == "My Content"

    def test_timestamps_set(self, notes_db):
        note_id = notes_db.save_note(title="T", content="C")
        note = notes_db.get_note(note_id)
        assert note["created_at"] is not None
        assert note["updated_at"] is not None

    def test_multiple_notes_get_unique_ids(self, notes_db):
        id1 = notes_db.save_note(title="Note 1", content="Content 1")
        id2 = notes_db.save_note(title="Note 2", content="Content 2")
        assert id1 != id2


class TestSaveNoteWithTags:
    def test_tags_stored(self, notes_db):
        note_id = notes_db.save_note(
            title="Tagged", content="Content", tags=["oncology", "cea"]
        )
        note = notes_db.get_note(note_id)
        assert sorted(note["tags"]) == ["cea", "oncology"]

    def test_empty_tags(self, notes_db):
        note_id = notes_db.save_note(title="No Tags", content="Content", tags=[])
        note = notes_db.get_note(note_id)
        assert note["tags"] == []

    def test_duplicate_tags_ignored(self, notes_db):
        note_id = notes_db.save_note(
            title="Dupes", content="Content", tags=["a", "a", "b"]
        )
        note = notes_db.get_note(note_id)
        assert sorted(note["tags"]) == ["a", "b"]

    def test_whitespace_tags_stripped(self, notes_db):
        note_id = notes_db.save_note(
            title="Spaces", content="Content", tags=["  foo  ", "bar"]
        )
        note = notes_db.get_note(note_id)
        assert sorted(note["tags"]) == ["bar", "foo"]

    def test_empty_string_tags_skipped(self, notes_db):
        note_id = notes_db.save_note(
            title="Blanks", content="Content", tags=["", "  ", "valid"]
        )
        note = notes_db.get_note(note_id)
        assert note["tags"] == ["valid"]


class TestSaveNoteWithRef:
    def test_ref_stored(self, notes_db):
        note_id = notes_db.save_note(
            title="Linked", content="Analysis of lab",
            ref_table="lab_results", ref_id=42,
        )
        note = notes_db.get_note(note_id)
        assert note["ref_table"] == "lab_results"
        assert note["ref_id"] == 42

    def test_no_ref(self, notes_db):
        note_id = notes_db.save_note(title="Unlinked", content="General note")
        note = notes_db.get_note(note_id)
        assert note["ref_table"] is None
        assert note["ref_id"] is None


class TestUpdateNote:
    def test_update_content(self, notes_db):
        note_id = notes_db.save_note(title="Original", content="V1")
        notes_db.save_note(title="Updated", content="V2", note_id=note_id)
        note = notes_db.get_note(note_id)
        assert note["title"] == "Updated"
        assert note["content"] == "V2"

    def test_update_changes_updated_at(self, notes_db):
        note_id = notes_db.save_note(title="T", content="C")
        note1 = notes_db.get_note(note_id)
        # Update
        notes_db.save_note(title="T2", content="C2", note_id=note_id)
        note2 = notes_db.get_note(note_id)
        assert note2["updated_at"] >= note1["updated_at"]

    def test_update_preserves_created_at(self, notes_db):
        note_id = notes_db.save_note(title="T", content="C")
        original = notes_db.get_note(note_id)
        notes_db.save_note(title="T2", content="C2", note_id=note_id)
        updated = notes_db.get_note(note_id)
        assert updated["created_at"] == original["created_at"]

    def test_update_returns_same_id(self, notes_db):
        note_id = notes_db.save_note(title="T", content="C")
        returned_id = notes_db.save_note(title="T2", content="C2", note_id=note_id)
        assert returned_id == note_id


class TestUpdateNoteTags:
    def test_replaces_tags(self, notes_db):
        note_id = notes_db.save_note(
            title="T", content="C", tags=["old1", "old2"]
        )
        notes_db.save_note(
            title="T", content="C", tags=["new1"], note_id=note_id
        )
        note = notes_db.get_note(note_id)
        assert note["tags"] == ["new1"]

    def test_clear_tags(self, notes_db):
        note_id = notes_db.save_note(
            title="T", content="C", tags=["tag1"]
        )
        notes_db.save_note(title="T", content="C", tags=[], note_id=note_id)
        note = notes_db.get_note(note_id)
        assert note["tags"] == []


class TestGetNote:
    def test_get_all_fields(self, notes_db):
        note_id = notes_db.save_note(
            title="Full Note", content="Body text",
            tags=["alpha", "beta"], ref_table="encounters", ref_id=7,
        )
        note = notes_db.get_note(note_id)
        assert note["id"] == note_id
        assert note["title"] == "Full Note"
        assert note["content"] == "Body text"
        assert note["ref_table"] == "encounters"
        assert note["ref_id"] == 7
        assert sorted(note["tags"]) == ["alpha", "beta"]
        assert "created_at" in note
        assert "updated_at" in note

    def test_not_found(self, notes_db):
        assert notes_db.get_note(99999) is None


class TestSearchByQuery:
    def test_match_title(self, notes_db):
        notes_db.save_note(title="CEA Trend Analysis", content="boring body")
        results = notes_db.search_notes_personal(query="CEA")
        assert len(results) == 1
        assert results[0]["title"] == "CEA Trend Analysis"

    def test_match_content(self, notes_db):
        notes_db.save_note(title="Generic", content="The hemoglobin is trending down")
        results = notes_db.search_notes_personal(query="hemoglobin")
        assert len(results) == 1

    def test_case_insensitive(self, notes_db):
        notes_db.save_note(title="CEA", content="test")
        results = notes_db.search_notes_personal(query="cea")
        assert len(results) == 1

    def test_no_match(self, notes_db):
        notes_db.save_note(title="X", content="Y")
        results = notes_db.search_notes_personal(query="nonexistent")
        assert results == []


class TestSearchByTag:
    def test_filter_by_tag(self, notes_db):
        notes_db.save_note(title="A", content="A", tags=["oncology"])
        notes_db.save_note(title="B", content="B", tags=["cardiology"])
        results = notes_db.search_notes_personal(tag="oncology")
        assert len(results) == 1
        assert results[0]["title"] == "A"

    def test_no_matching_tag(self, notes_db):
        notes_db.save_note(title="A", content="A", tags=["x"])
        results = notes_db.search_notes_personal(tag="nonexistent")
        assert results == []


class TestSearchByRef:
    def test_filter_by_ref(self, notes_db):
        notes_db.save_note(title="A", content="A", ref_table="lab_results", ref_id=1)
        notes_db.save_note(title="B", content="B", ref_table="encounters", ref_id=2)
        results = notes_db.search_notes_personal(ref_table="lab_results", ref_id=1)
        assert len(results) == 1
        assert results[0]["title"] == "A"

    def test_ref_table_only(self, notes_db):
        notes_db.save_note(title="A", content="A", ref_table="lab_results", ref_id=1)
        notes_db.save_note(title="B", content="B", ref_table="lab_results", ref_id=2)
        notes_db.save_note(title="C", content="C", ref_table="encounters", ref_id=1)
        results = notes_db.search_notes_personal(ref_table="lab_results")
        assert len(results) == 2


class TestSearchCombined:
    def test_tag_and_query(self, notes_db):
        notes_db.save_note(title="CEA Analysis", content="trend", tags=["oncology"])
        notes_db.save_note(title="CEA Other", content="other", tags=["cardiology"])
        notes_db.save_note(title="Blood Pressure", content="bp", tags=["oncology"])
        results = notes_db.search_notes_personal(query="CEA", tag="oncology")
        assert len(results) == 1
        assert results[0]["title"] == "CEA Analysis"


class TestSearchEmpty:
    def test_no_notes_returns_empty(self, notes_db):
        results = notes_db.search_notes_personal()
        assert results == []


class TestSearchReturnsPreview:
    def test_content_preview_truncated(self, notes_db):
        long_content = "A" * 500
        notes_db.save_note(title="Long", content=long_content)
        results = notes_db.search_notes_personal()
        assert len(results[0]["content_preview"]) == 300


class TestDeleteNote:
    def test_delete_existing(self, notes_db):
        note_id = notes_db.save_note(title="T", content="C")
        assert notes_db.delete_note(note_id) is True
        assert notes_db.get_note(note_id) is None

    def test_delete_nonexistent(self, notes_db):
        assert notes_db.delete_note(99999) is False

    def test_delete_cascades_tags(self, notes_db):
        note_id = notes_db.save_note(title="T", content="C", tags=["a", "b"])
        notes_db.delete_note(note_id)
        # Verify tags are gone too
        tag_rows = notes_db.query(
            "SELECT * FROM note_tags WHERE note_id = ?", (note_id,)
        )
        assert tag_rows == []


class TestSearchOrderedByUpdated:
    def test_most_recent_first(self, notes_db):
        id1 = notes_db.save_note(title="First", content="C1")
        id2 = notes_db.save_note(title="Second", content="C2")
        results = notes_db.search_notes_personal()
        assert results[0]["title"] == "Second"
        assert results[1]["title"] == "First"

    def test_updated_note_moves_to_top(self, notes_db):
        id1 = notes_db.save_note(title="First", content="C1")
        id2 = notes_db.save_note(title="Second", content="C2")
        # Update first note — it should now appear before second
        notes_db.save_note(title="First Updated", content="C1v2", note_id=id1)
        results = notes_db.search_notes_personal()
        assert results[0]["title"] == "First Updated"
