def test_orchestrator_total_value_not_from_account_balances():
    """account_balances has no `total_value` column (only cash, buying_power);
    the portfolio total must come from positions equity instead.
    """
    import re

    import src.analysis.orchestrator as orch

    collapsed = re.sub(r"\s+", " ", __import__("inspect").getsource(orch))
    assert "SUM(total_value)" not in collapsed
