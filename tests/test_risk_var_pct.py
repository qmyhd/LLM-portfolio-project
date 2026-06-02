from datetime import datetime


def test_portfolio_risk_report_has_var_pct_fields():
    from src.analysis.models import PortfolioRiskReport

    r = PortfolioRiskReport(
        var_95_1d=100.0,
        var_95_5d=224.0,
        var_95_1d_pct=2.5,
        var_95_5d_pct=5.59,
        concentration_hhi=0.10,
        diversification_ratio=1.2,
        correlation_matrix={},
        top_risk_contributors=[],
        sector_exposure={},
        computed_at=datetime(2026, 6, 1),
        data_sources=["ohlcv"],
    )
    assert r.var_95_1d_pct == 2.5
    assert r.var_95_5d_pct == 5.59


def test_var_pct_defaults_are_non_breaking():
    # Existing construction sites that omit the new fields must still work.
    from src.analysis.models import PortfolioRiskReport

    r = PortfolioRiskReport(
        var_95_1d=0.0,
        var_95_5d=0.0,
        concentration_hhi=0.0,
        diversification_ratio=0.0,
        correlation_matrix={},
        top_risk_contributors=[],
        sector_exposure={},
        computed_at=datetime(2026, 6, 1),
        data_sources=[],
    )
    assert r.var_95_1d_pct == 0.0
    assert r.var_95_5d_pct == 0.0
