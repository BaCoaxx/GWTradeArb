from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    path = FIXTURES / name
    return json.loads(path.read_text(encoding="utf-8"))
