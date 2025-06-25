import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "data" / "database" / "price_history.db"


def get_connection(path: Path = DB_PATH):
    """Return a SQLite connection to the project database."""
    return sqlite3.connect(path)
