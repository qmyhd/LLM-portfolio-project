from src.analysis.models import IdeaData


def test_ideadata_has_author_id_default_empty():
    idea = IdeaData(direction="long", confidence=0.8, labels=[], idea_text="x", created_at="2026-06-01", author="alice")
    assert idea.author_id == ""  # safe neutral default — resolver treats "" as no identity


def test_ideadata_accepts_author_id():
    idea = IdeaData(direction="long", confidence=0.8, labels=[], idea_text="x", created_at="2026-06-01", author="alice", author_id="419660638881579028")
    assert idea.author_id == "419660638881579028"


def test_orchestrator_threads_author_id():
    from src.analysis import orchestrator as orch
    row = {"direction": "long", "confidence": 0.9, "labels": [], "idea_text": "buy",
           "created_at": "2026-06-01", "author": "alice", "author_id": 419660638881579028}
    ideas = orch._assemble_ideas([type("R", (), {"_mapping": row})()])
    assert ideas[0].author_id == "419660638881579028"
    assert ideas[0].author == "alice"
