#!/usr/bin/env python3
"""
Fix orphaned SnapTrade accounts  -- mark stale re-link duplicates as 'deleted'.

Background:
  When a user re-links Robinhood in SnapTrade, new account IDs are created under
  a new brokerage_authorization.  The old accounts stop syncing but their stale
  positions remain, causing double-counted portfolio values.

  This script detects duplicate account numbers (same brokerage account appearing
  under multiple authorizations) and marks the older ones as 'deleted'.

  NO DATA IS REMOVED  -- positions/orders/balances are preserved.  The portfolio
  endpoint already excludes positions from deleted accounts.

Usage:
    python scripts/fix_orphaned_accounts.py          # dry-run (default)
    python scripts/fix_orphaned_accounts.py --apply  # actually mark accounts
    python scripts/fix_orphaned_accounts.py --revert # undo: set back to 'connected'
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.env_bootstrap import bootstrap_env  # noqa: E402

bootstrap_env()

from src.db import execute_sql  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix orphaned SnapTrade accounts")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true", help="Actually mark old accounts as deleted")
    group.add_argument("--revert", action="store_true", help="Set all accounts back to connected")
    args = parser.parse_args()

    print("=" * 70)
    print("  Orphaned Account Detector")
    print("=" * 70)

    # Find accounts sharing the same account number but different brokerage_authorization
    accts = execute_sql(
        """
        SELECT id, number, name, brokerage_authorization,
               last_successful_sync, connection_status,
               (SELECT COUNT(*) FROM positions WHERE account_id = a.id AND quantity > 0) as active_positions
        FROM accounts a
        ORDER BY number, last_successful_sync DESC NULLS LAST
        """,
        fetch_results=True,
    )

    # Group by account number
    by_number: dict[str, list[dict]] = {}
    for r in accts:
        d = dict(r._mapping)
        num = d["number"]
        by_number.setdefault(num, []).append(d)

    orphans: list[str] = []

    for number, group in by_number.items():
        if len(group) < 2:
            print(f"\n  Account #{number}: single entry  -- OK")
            d = group[0]
            print(
                f"    {d['id'][:12]}...  auth={str(d['brokerage_authorization'])[:12]}  "
                f"status={d['connection_status']}  sync={str(d['last_successful_sync'])[:19]}  "
                f"positions={d['active_positions']}"
            )
            continue

        # Multiple accounts for same number  -- newest sync is the active one
        print(f"\n  Account #{number}: {len(group)} entries  -- DUPLICATE")
        newest = group[0]  # Already sorted by last_successful_sync DESC
        for i, d in enumerate(group):
            is_active = i == 0
            marker = "ACTIVE" if is_active else "ORPHAN"
            print(
                f"    [{marker}] {d['id'][:12]}...  auth={str(d['brokerage_authorization'])[:12]}  "
                f"status={d['connection_status']}  sync={str(d['last_successful_sync'])[:19]}  "
                f"positions={d['active_positions']}"
            )
            if not is_active:
                orphans.append(d["id"])

    if not orphans:
        print("\n  No orphaned accounts found.")
        return

    print(f"\n  Found {len(orphans)} orphaned account(s) to mark as 'deleted'")

    if args.revert:
        # Revert all to connected
        for acct_id in orphans:
            execute_sql(
                "UPDATE accounts SET connection_status = 'connected', "
                "connection_disabled_at = NULL WHERE id = :id",
                {"id": acct_id},
            )
            print(f"    Reverted {acct_id[:12]}... -> connected")
        print("\n  Done. All accounts set back to 'connected'.")
        return

    if not args.apply:
        print("\n  DRY RUN  -- pass --apply to execute changes")
        print("  Pass --revert to undo previous changes")
        return

    # Apply: mark orphans as deleted
    for acct_id in orphans:
        execute_sql(
            "UPDATE accounts SET connection_status = 'deleted', "
            "connection_disabled_at = NOW() WHERE id = :id",
            {"id": acct_id},
        )
        print(f"    Marked {acct_id[:12]}... -> deleted")

    print(f"\n  Done. {len(orphans)} orphaned account(s) marked as 'deleted'.")
    print("  Portfolio endpoint will now exclude their positions.")
    print("  Run with --revert to undo if needed.")


if __name__ == "__main__":
    main()
