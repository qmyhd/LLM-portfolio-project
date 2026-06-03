from src.analysis.models import IdeaData


def test_ideadata_has_author_id_default_empty():
    idea = IdeaData(direction="long", confidence=0.8, labels=[], idea_text="x", created_at="2026-06-01", author="alice")
    assert idea.author_id == ""  # safe neutral default — resolver treats "" as no identity


def test_ideadata_accepts_author_id():
    idea = IdeaData(direction="long", confidence=0.8, labels=[], idea_text="x", created_at="2026-06-01", author="alice", author_id="419660638881579028")
    assert idea.author_id == "419660638881579028"
