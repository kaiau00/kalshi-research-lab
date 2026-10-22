#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from market_shrunk_price_band_holdout.study import public_summary, run_study


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--unlock-holdout", action="store_true")
    args = parser.parse_args()
    if args.output.exists() or args.summary.exists():
        raise ValueError("Study 026 output already exists; refusing to overwrite a holdout disclosure")
    report = run_study(args.database, args.audit, unlock_holdout=args.unlock_holdout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.summary.write_text(json.dumps(public_summary(report), indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "state": report["state"],
                "all_holdout_gates_passed": report["all_holdout_gates_passed"],
                "registration_sha256": report["registration_sha256"],
                "report_sha256": report["report_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
