from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "public" / "demo-snapshot.json"
sys.path.insert(0, str(ROOT))

from autocore.companion import public_companion_status
from autocore.demo import demo_snapshot
from autocore.taskpacks import list_task_packs


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps({"demo": demo_snapshot(ROOT)}, indent=2) + "\n", encoding="utf-8")
    (TARGET.parent / "task-packs.json").write_text(
        json.dumps({"task_packs": list_task_packs()}, indent=2) + "\n",
        encoding="utf-8",
    )
    from autocore.setup import public_setup_status

    (TARGET.parent / "setup-status.json").write_text(
        json.dumps({"setup": public_setup_status()}, indent=2) + "\n",
        encoding="utf-8",
    )
    (TARGET.parent / "companion-status.json").write_text(
        json.dumps({"companion": public_companion_status()}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
