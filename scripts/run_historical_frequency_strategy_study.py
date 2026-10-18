#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from historical_frequency_optimization.study import public_summary, run_study


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    def progress(done: int, total: int):
        print(f"Study 021 grid: {done}/{total}", flush=True)

    report = run_study(args.database, args.audit, progress=progress)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.summary.write_text(json.dumps(public_summary(report), indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "state": report["state"],
                "configurations_evaluated": report["configurations_evaluated"],
                "development_gate_passers": report["development_gate_passers"],
                "risk_recommendation": report["risk_recommendation"],
                "registration_sha256": report["registration_sha256"],
                "report_sha256": report["report_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
