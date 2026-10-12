#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from rollover_bridge.runner import RolloverRunner


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-segments", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.max_segments <= 100:
        raise ValueError("max-segments must be between 1 and 100")
    runner = RolloverRunner()
    processed = 0
    outcome = "idle"
    try:
        while processed < args.max_segments:
            outcome = runner.process_next()
            if outcome != "processed":
                break
            processed += 1
        print(json.dumps({
            "outcome": outcome,
            "processed_segments": processed,
            "next_segment": runner.next_segment,
            "last_digest": runner.last_digest,
        }, sort_keys=True))
    finally:
        runner.close()


if __name__ == "__main__":
    main()
