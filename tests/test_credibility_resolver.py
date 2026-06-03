from src.analysis.credibility import CredibilityResult, blend_multiplier

MULTS = {"S": 1.35, "A": 1.15, "B": 1.00, "C": 0.75, "D": 0.45}


def test_no_tags_is_neutral():
    r = blend_multiplier(tags={}, tiers={}, multipliers=MULTS)
    assert r.multiplier == 1.0 and r.muted_out is False


def test_untiered_category_is_neutral_term():
    r = blend_multiplier(tags={"markets": 0.6, "geopolitics": 0.4}, tiers={}, multipliers=MULTS)
    assert r.multiplier == 1.0


def test_normal_blend():
    r = blend_multiplier(tags={"markets": 0.6, "geopolitics": 0.4},
                         tiers={"markets": ("A", False), "geopolitics": ("S", False)}, multipliers=MULTS)
    assert round(r.multiplier, 4) == 1.23


def test_weights_normalized_at_read_time():
    r = blend_multiplier(tags={"markets": 6, "geopolitics": 4},
                         tiers={"markets": ("A", False), "geopolitics": ("S", False)}, multipliers=MULTS)
    assert round(r.multiplier, 4) == 1.23


def test_partial_mute_drags_then_clamps():
    r = blend_multiplier(tags={"markets": 0.6, "geopolitics": 0.4},
                         tiers={"markets": ("A", False), "geopolitics": ("S", True)}, multipliers=MULTS)
    assert round(r.multiplier, 4) == 0.69


def test_partial_mute_clamps_low():
    r = blend_multiplier(tags={"markets": 0.9, "geopolitics": 0.1},
                         tiers={"markets": ("A", True), "geopolitics": ("D", False)}, multipliers=MULTS)
    assert r.multiplier == 0.30
    assert r.muted_out is False


def test_clamp_high():
    r = blend_multiplier(tags={"markets": 1.0}, tiers={"markets": ("S", False)},
                         multipliers={**MULTS, "S": 2.0})
    assert r.multiplier == 1.50


def test_fully_muted_is_zero_not_clamped():
    r = blend_multiplier(tags={"markets": 0.6, "geopolitics": 0.4},
                         tiers={"markets": ("A", True), "geopolitics": ("S", True)}, multipliers=MULTS)
    assert r.multiplier == 0.0 and r.muted_out is True


def test_contributor_tiers_recorded():
    r = blend_multiplier(tags={"markets": 0.6, "geopolitics": 0.4},
                         tiers={"markets": ("A", False), "geopolitics": ("S", False)}, multipliers=MULTS)
    assert r.tiers == {"markets": "A", "geopolitics": "S"}


import src.analysis.credibility as cred


def _mock_execute(rows_by_marker):
    """Return a fake execute_sql that dispatches on a substring of the query."""
    def _fake(query, params=None, fetch_results=False):
        for marker, rows in rows_by_marker.items():
            if marker in query:
                return [type("R", (), {"_mapping": row})() for row in rows]
        return []
    return _fake


def test_resolver_unknown_author_is_neutral(monkeypatch):
    monkeypatch.setattr(cred, "execute_sql", _mock_execute({}))
    r = cred.CredibilityResolver.for_ideas("AAPL", author_ids=["999"])
    res = r.multiplier("999")
    assert res.multiplier == 1.0 and res.person_id is None


def test_resolver_blank_author_is_neutral(monkeypatch):
    monkeypatch.setattr(cred, "execute_sql", _mock_execute({}))
    r = cred.CredibilityResolver.for_ideas("AAPL", author_ids=[""])
    assert r.multiplier("").multiplier == 1.0


def test_resolver_happy_path(monkeypatch):
    rows = {
        "tier_multipliers": [{"tier": "S", "multiplier": 1.35}, {"tier": "A", "multiplier": 1.15}],
        "stock_topic_tags": [{"category_slug": "markets", "weight": 0.6},
                             {"category_slug": "geopolitics", "weight": 0.4}],
        "source_identities": [{"platform_user_id": "1", "person_id": 7, "full_name": "Sachs"}],
        "person_category_tiers": [{"person_id": 7, "category_slug": "markets", "tier": "A", "muted": False},
                                  {"person_id": 7, "category_slug": "geopolitics", "tier": "S", "muted": False}],
    }
    monkeypatch.setattr(cred, "execute_sql", _mock_execute(rows))
    r = cred.CredibilityResolver.for_ideas("LMT", author_ids=["1"])
    res = r.multiplier("1")
    assert round(res.multiplier, 4) == 1.23
    assert res.person_id == 7 and res.person_name == "Sachs"


def test_resolver_is_failsafe_on_db_error(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(cred, "execute_sql", _boom)
    r = cred.CredibilityResolver.for_ideas("AAPL", author_ids=["1"])
    assert r.multiplier("1").multiplier == 1.0   # never raises; neutral


def test_resolver_batches_identity_lookup(monkeypatch):
    calls = {"n": 0}
    def _counting(query, params=None, fetch_results=False):
        calls["n"] += 1
        return []
    monkeypatch.setattr(cred, "execute_sql", _counting)
    cred.CredibilityResolver.for_ideas("AAPL", author_ids=["1", "2", "3", "1"])
    # batched: a small bounded number of queries, NOT one per author
    assert calls["n"] <= 4
