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
