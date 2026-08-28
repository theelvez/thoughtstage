"""One-shot Compose demo runner for the mock hello-stage experiment."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

RUN_ID = "hello-stage-demo"
MANIFEST = Path("examples/hello-stage/experiment.yaml")
BUNDLE = Path("runs") / RUN_ID


def main() -> int:
    BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(BUNDLE, ignore_errors=True)
    completed = subprocess.run(
        ["thoughtstage", "run", str(MANIFEST), "--run-id", RUN_ID],
        check=False,
    )
    if completed.returncode != 0:
        return completed.returncode
    print(f"Observer: http://localhost:3000/?run={RUN_ID}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
