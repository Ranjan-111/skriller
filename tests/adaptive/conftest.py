"""Load the existing real PostgreSQL fixture without duplicating its bootstrap."""

import runpy
from pathlib import Path

database = runpy.run_path(str(Path(__file__).resolve().parents[1] / "db" / "conftest.py"))[
    "database"
]
