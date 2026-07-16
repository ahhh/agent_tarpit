import sys
from pathlib import Path

# Make the honeymesh package importable when tests run from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
