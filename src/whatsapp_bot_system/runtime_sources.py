from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_runtime_input_from_file(path: str | Path) -> dict[str, Any]:
    runtime_path = Path(path)
    data = json.loads(runtime_path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Runtime file must contain a JSON object')
    return data
