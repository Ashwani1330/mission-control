"""mission-control [runs_dir]"""

import argparse
from pathlib import Path

from mission_control.app import MissionControl


def main() -> None:
    parser = argparse.ArgumentParser(prog="mission-control", description="Mission Control: watch pipeline runs live.")
    parser.add_argument("runs_dir", nargs="?", type=Path, default=Path("runs"),
                        help="folder holding <workflow>/<run-id>/events.jsonl (default: ./runs)")
    parser.add_argument("--config", type=Path, help="mission-control.toml listing workflows to launch "
                        "(default: ./mission-control.toml, else one next to the runs folder)")
    args = parser.parse_args()
    if not args.runs_dir.is_dir():
        parser.error(f"not a folder: {args.runs_dir}")
    MissionControl(args.runs_dir.resolve(), args.config).run()


if __name__ == "__main__":
    main()
