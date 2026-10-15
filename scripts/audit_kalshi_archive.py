from __future__ import annotations

import argparse
import json
from pathlib import Path

from historical_archive.audit import audit
from research_lab.research import write_json


def main():
    parser = argparse.ArgumentParser(description="Audit a downloaded official KXBTC15M archive")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.db)
    write_json(args.output, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

