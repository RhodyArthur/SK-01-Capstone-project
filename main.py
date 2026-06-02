"""Module entrypoint for running the Multi-Source HR Data Integration pipeline."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from pipeline import run_pipeline

if __name__ == "__main__":
    run_pipeline()
