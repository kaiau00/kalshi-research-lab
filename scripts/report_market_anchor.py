import argparse
import json
from pathlib import Path

from market_anchor_study.report import checkpoint_report
from research_lab.storage import canonical


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--phase", default="development")
    parser.add_argument("--created-after-ns", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = checkpoint_report(
        args.checkpoint,
        args.account,
        phase=args.phase,
        created_after_ns=args.created_after_ns,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical(report))
    print(json.dumps({"output": str(args.output), "results": report["results"]}, indent=2))


if __name__ == "__main__":
    main()

