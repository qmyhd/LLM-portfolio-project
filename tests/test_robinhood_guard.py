"""Robinhood MCP read-only guard stays in sync with the pinned live tool list.

Checks .claude/hooks/robinhood_readonly_guard.py against docs/integrations/robinhood-mcp-tools.json
and the deny rules in .claude/settings.json. No network, no MCP calls.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK_PATH = ROOT / ".claude" / "hooks" / "robinhood_readonly_guard.py"
SNAPSHOT = json.loads((ROOT / "docs" / "integrations" / "robinhood-mcp-tools.json").read_text(encoding="utf-8"))
SETTINGS = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
SERVER = SNAPSHOT["server"]


def _load_hook():
    spec = importlib.util.spec_from_file_location("robinhood_readonly_guard", HOOK_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_hook()


@pytest.mark.parametrize("tool", SNAPSHOT["read"])
def test_read_tools_allowed(tool):
    assert guard.decide(f"mcp__{SERVER}__{tool}") is None


@pytest.mark.parametrize("tool", sorted(set(SNAPSHOT["write"]) | set(SNAPSHOT["deny_rule_tools"])))
def test_write_tools_blocked(tool):
    reason = guard.decide(f"mcp__{SERVER}__{tool}")
    assert reason and "Blocked by robinhood_readonly_guard" in reason


def test_unknown_future_tool_blocked():
    assert guard.decide(f"mcp__{SERVER}__transfer_funds") is not None


def test_other_servers_untouched():
    assert guard.decide("mcp__claude_ai_Supabase__execute_sql") is None
    assert guard.decide("Bash") is None


def test_read_and_write_lists_disjoint():
    assert not set(SNAPSHOT["read"]) & set(SNAPSHOT["write"])


def test_settings_deny_rules_match_snapshot():
    denied = {
        rule.removeprefix(f"mcp__{SERVER}__")
        for rule in SETTINGS["permissions"]["deny"]
        if rule.startswith(f"mcp__{SERVER}__")
    }
    assert denied == set(SNAPSHOT["deny_rule_tools"])


def test_settings_wire_project_hook():
    entries = SETTINGS["hooks"]["PreToolUse"]
    commands = [h["command"] for e in entries if "obinhood" in e["matcher"] for h in e["hooks"]]
    assert any("robinhood_readonly_guard.py" in c for c in commands)
    assert all(h.get("onFailure") == "block" for e in entries for h in e["hooks"])


def test_hook_fails_closed_on_bad_input():
    proc = subprocess.run([sys.executable, str(HOOK_PATH)], input=b"not json", capture_output=True)
    assert proc.returncode == 2


def test_hook_emits_deny_json_for_place_order():
    payload = json.dumps({"tool_name": f"mcp__{SERVER}__place_equity_order", "tool_input": {}}).encode()
    proc = subprocess.run([sys.executable, str(HOOK_PATH)], input=payload, capture_output=True)
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
