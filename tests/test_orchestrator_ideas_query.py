def test_orchestrator_ideas_query_uses_real_columns():
    """The discord_parsed_ideas query must use primary_symbol + a join to
    discord_messages (author/created_at live there), not the non-existent
    `ticker`/`created_at`/`author` columns on discord_parsed_ideas.
    """
    import inspect

    import src.analysis.orchestrator as orch

    src = inspect.getsource(orch)
    assert "dpi.primary_symbol" in src
    assert "LEFT JOIN discord_messages" in src
    assert "UPPER(ticker)" not in src
