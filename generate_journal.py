"""Compatibility entry point for the journal generator.

The package entry point lives at `src.journal_generator:main`; this file keeps
older deploy checks and scripts that call `python generate_journal.py` working.
"""

from src.journal_generator import main


if __name__ == "__main__":
    main()
