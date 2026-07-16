"""HoneyMesh — a defensive honeypot for detecting LLM-guided attack harnesses.

Deploy only on systems you own or are explicitly authorized to monitor. See the
design docs (README.md, ARCHITECTURE.md, DECOY_DESIGN.md, DETECTION_AND_SCORING.md,
OPERATIONS_RUNBOOK.md, EVALUATION_PLAN.md) shipped with the pack.
"""

from .app import Engine, Reply, Request, create_app
from .config import Config

__version__ = "1.0.0"

__all__ = ["Engine", "Request", "Reply", "create_app", "Config", "__version__"]
