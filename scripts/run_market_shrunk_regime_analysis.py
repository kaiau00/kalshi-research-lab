#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from market_shrunk_regime_analysis.study import public_summary, run_study


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    report = run_study(args.database, args.audit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.summary.write_text(json.dumps(public_summary(report), indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "state": report["state"],
                "repeatable_weaknesses": len(report["repeatable_weaknesses"]),
                "repeatable_strengths": len(report["repeatable_strengths"]),
                "partition_sign_instabilities": len(report["partition_sign_instabilities"]),
                "registration_sha256": report["registration_sha256"],
                "report_sha256": report["report_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
