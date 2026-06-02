from datetime import date

from src.portfolio_returns import compute_return_series, period_window


def test_period_window_basic():
    today = date(2026, 6, 1)
    assert period_window("1W", today) == date(2026, 5, 25)
    assert period_window("YTD", today) == date(2026, 1, 1)
    assert period_window("1M", today) == date(2026, 5, 2)
    assert period_window("unknown", today) == date(2026, 5, 2)  # default 1M


def test_single_holding_equals_price_return():
    points, period = compute_return_series(
        {"AAPL": 10.0},
        {"AAPL": {"2026-05-01": 100.0, "2026-05-02": 110.0}},
    )
    assert points[0] == {"date": "2026-05-01", "returnPct": 0.0}
    assert points[-1]["returnPct"] == 10.0
    assert period == 10.0


def test_quantity_scaling_is_invariant_flow_free():
    series = {
        "AAPL": {"2026-05-01": 100.0, "2026-05-02": 110.0},
        "MSFT": {"2026-05-01": 200.0, "2026-05-02": 210.0},
    }
    a, ra = compute_return_series({"AAPL": 10, "MSFT": 5}, series)
    b, rb = compute_return_series({"AAPL": 1000, "MSFT": 500}, series)
    assert a == b and ra == rb


def test_baseline_is_zero_at_window_start():
    points, _ = compute_return_series(
        {"AAPL": 1.0, "MSFT": 1.0},
        {
            "AAPL": {"2026-05-01": 100.0, "2026-05-02": 110.0},
            "MSFT": {"2026-05-01": 50.0, "2026-05-02": 55.0},
        },
    )
    assert points[0]["returnPct"] == 0.0


def test_short_history_holding_renormalizes_no_jump():
    points, _ = compute_return_series(
        {"AAPL": 1.0, "NEW": 1.0},
        {
            "AAPL": {"2026-05-01": 100.0, "2026-05-02": 100.0, "2026-05-03": 110.0},
            "NEW": {"2026-05-03": 200.0},  # only present on the last day
        },
    )
    # Early dates: only AAPL has data -> reflects AAPL alone (flat 0%).
    assert points[0]["returnPct"] == 0.0
    assert points[1]["returnPct"] == 0.0
    # Last date: AAPL +10% (weight 110), NEW 0% (weight 200) -> blended.
    assert points[2]["returnPct"] == round((110 / 310) * 10.0, 4)


def test_empty_inputs_return_zero():
    assert compute_return_series({}, {}) == ([], 0.0)
    assert compute_return_series({"AAPL": 5}, {}) == ([], 0.0)
