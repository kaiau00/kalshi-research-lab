#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from historical_backtest.screen import run_screen


def main():
    parser = argparse.ArgumentParser(description="Run preregistered historical candle screen 018")
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run_screen(args.database, args.audit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "state": report["state"],
                "registration_sha256": report["registration_sha256"],
                "report_sha256": report["report_sha256"],
                "output": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
