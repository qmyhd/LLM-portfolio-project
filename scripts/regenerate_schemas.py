#!/usr/bin/env python3
"""
Regenerate Schema Dataclasses with Post-Migration Types
======================================================

This script regenerates src/generated_schemas.py with proper datetime types
that match the post-migration database schema (after migration 017).

The issue: schema_parser.py only reads baseline schema, ignoring migrations,
so generated schemas show sync_timestamp: str instead of sync_timestamp: datetime

This script fixes the type mappings to match actual database schema.
"""

import sys
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))


def update_generated_schemas():
    """Update generated schemas with correct datetime types."""

    schema_file = project_root / "src" / "generated_schemas.py"

    # Read current content
    with open(schema_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Type corrections for post-migration schema
    corrections = {
        "sync_timestamp: str": "sync_timestamp: datetime",
        "sync_timestamp: Optional[str]": "sync_timestamp: Optional[datetime]",
        "snapshot_date: str": "snapshot_date: date",
        "snapshot_date: Optional[str]": "snapshot_date: Optional[date]",
        "applied_at: Optional[datetime]": "applied_at: Optional[datetime]",  # Already correct
        "created_at: Optional[datetime]": "created_at: Optional[datetime]",  # Already correct
        "from datetime import": "from datetime import datetime, date, timezone",  # Ensure imports
    }

    # Apply corrections
    updated_content = content
    changes_made = []

    for old_type, new_type in corrections.items():
        if old_type in updated_content and old_type != new_type:
            updated_content = updated_content.replace(old_type, new_type)
            changes_made.append(f"  • {old_type} → {new_type}")

    # Ensure proper imports at top
    if "from datetime import datetime, date" not in updated_content:
        # Find the first import and add datetime imports
        lines = updated_content.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("from datetime import"):
                lines[i] = "from datetime import datetime, date, timezone"
                break
            elif line.startswith("from typing import"):
                # Insert datetime import before typing
                lines.insert(i, "from datetime import datetime, date, timezone")
                break
        updated_content = "\n".join(lines)
        changes_made.append("  • Added proper datetime imports")

    # Write updated content
    if changes_made:
        with open(schema_file, "w", encoding="utf-8") as f:
            f.write(updated_content)

        print("✅ Updated generated_schemas.py with post-migration types:")
        for change in changes_made:
            print(change)
        print(f"\n📄 File updated: {schema_file}")
        return True
    else:
        print("✅ generated_schemas.py already has correct types")
        return False


if __name__ == "__main__":
    print("🔧 Regenerating schemas with post-migration types...")
    updated = update_generated_schemas()

    if updated:
        print("\n🎯 Schema alignment complete!")
        print("Generated schemas now match post-migration database state")
    else:
        print("\n✅ No changes needed - schemas already aligned")
