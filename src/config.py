import logging
from pathlib import Path
from typing import Any


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("pipeline.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

def build_config() -> dict[str, Any]:
    """Return pipeline configuration without executing side effects."""
    _src_dir = Path(__file__).parent
    return {
        "input_dir": _src_dir / "data" / "raw",
        "output_dir": _src_dir.parent / "output",
        "quality_threshold": 0.95,
        "source_priority": {"globaltech_hris": 1, "acquiredco_hris": 2, "benefits": 3, "payroll": 4},
    }


CONFIG = build_config()