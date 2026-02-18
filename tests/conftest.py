import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Clear DSN so tests run without a database
os.environ.pop("DATABASE_URL", None)
os.environ.pop("POSTGRES_CONNECTION_STRING", None)
