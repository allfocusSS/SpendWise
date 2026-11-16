"""The AI on-call responder (deploy/observability/oncall-responder/) is standard library only and
runs in its own container, so it isn't a package of the backend: put it on the import path here."""

import sys
from pathlib import Path

RESPONDER = Path(__file__).resolve().parents[3] / "deploy" / "observability" / "oncall-responder"
if str(RESPONDER) not in sys.path:
    sys.path.insert(0, str(RESPONDER))
