"""mission-control [runs_dir]"""

import argparse
from pathlib import Path

from mission_control.app import MissionControl


def main() -> None:
    parser = argparse.ArgumentParser(prog="mission-control", description="Mission Control: watch pipeline runs live.")
    parser.add_argument("runs_dir", nargs="?", type=Path, default=Path("runs"),
                        help="folder holding <workflow>/<run-id>/events.jsonl (default: ./runs)")
    args = parser.parse_args()
    if not args.runs_dir.is_dir():
        parser.error(f"not a folder: {args.runs_dir}")
    MissionControl(args.runs_dir.resolve()).run()


if __name__ == "__main__":
    main()
