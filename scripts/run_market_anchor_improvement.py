#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from market_anchor_improvement import development_report, load_frozen_checkpoint


def main():
    parser = argparse.ArgumentParser(description="Run read-only Market Anchor Improvement Study 008")
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = development_report(load_frozen_checkpoint(args.checkpoint))
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
