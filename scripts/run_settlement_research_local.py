#!/usr/bin/env python3
"""Run the frozen Studies 010/011 extraction locally and resumably."""
from __future__ import annotations

import argparse
import json

from settlement_research.runner import LocalSettlementResearchRunner, default_paths


def main():
    default_manifest, default_seed, default_root = default_paths()
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=default_manifest)
    parser.add_argument("--seed", default=default_seed)
    parser.add_argument("--root", default=default_root)
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--max-segments", type=int)
    parser.add_argument("--keep-archives", action="store_true")
    args = parser.parse_args()

    runner = LocalSettlementResearchRunner(
        args.manifest,
        args.seed,
        args.root,
        checkpoint_every=args.checkpoint_every,
        keep_archives=args.keep_archives,
    )
    processed = 0
    try:
        while args.max_segments is None or processed < args.max_segments:
            state = runner.process_next()
            if state == "processed":
                processed += 1
            print(json.dumps({
                "state": state,
                "processed_this_run": processed,
                "next_segment": runner.next_segment,
                "events_replayed": runner.tape.events,
                "rows": len(runner.tape.rows),
            }, sort_keys=True), flush=True)
            if state == "development_complete":
                break
    finally:
        runner.close()


if __name__ == "__main__":
    main()
