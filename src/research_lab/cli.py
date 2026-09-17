from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

from .settings import Experiment, db_path


def main():
    parser = argparse.ArgumentParser(description='BTC market research; no live trading capability')
    sub = parser.add_subparsers(dest='command', required=True)
    serve = sub.add_parser('serve', help='Recorder, protected dashboard and hourly fixed paper replay')
    serve.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8000')))
    sub.add_parser('record', help='Run the data collector only')
    replay = sub.add_parser('backtest', help='Replay recorded books and benchmark with simulated execution')
    replay.add_argument('--db', type=Path, default=db_path())
    replay.add_argument('--output', type=Path, default=Path('reports'))
    replay.add_argument('--config', type=Path)
    replay.add_argument('--split', choices=['train', 'validation', 'holdout', 'all', 'forward'], default='train')
    replay.add_argument('--unlock-holdout', action='store_true')
    replay.add_argument('--end-id', type=int)
    demo = sub.add_parser('demo', help='Synthetic pipeline test; not performance evidence')
    demo.add_argument('--output', type=Path, default=Path('reports/demo'))
    hist = sub.add_parser('history', help='Download historical quotes separately from live replay data')
    hist.add_argument('--db', type=Path, required=True)
    hist.add_argument('--days', type=int, default=2)
    hist.add_argument('--max-markets', type=int, default=192)
    screen = sub.add_parser('screen', help='Non-executable historical quote/outcome screen')
    screen.add_argument('--db', type=Path, required=True)
    screen.add_argument('--output', type=Path, default=Path('reports/historical-screen.json'))
    verify = sub.add_parser('verify', help='Verify raw event hash chain')
    verify.add_argument('--db', type=Path, default=db_path())
    backup = sub.add_parser('backup', help='Export a consistent SQLite snapshot and verify its hash chain')
    backup.add_argument('--db', type=Path, default=db_path())
    backup.add_argument('--output', type=Path, required=True)
    maintain = sub.add_parser('maintain', help='One bounded segment replay and verified archive')
    maintain.add_argument('--root', type=Path, required=True)
    restore = sub.add_parser('restore-segments', help='Restore verified sealed archives to a new SQLite file')
    restore.add_argument('--root', type=Path, required=True)
    restore.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    try:
        if args.command == 'serve':
            import uvicorn
            uvicorn.run('research_lab.app:create_app', factory=True, host='0.0.0.0', port=args.port, workers=1)
        elif args.command == 'record':
            from .recorder import Recorder
            asyncio.run(Recorder(db_path()).run())
        elif args.command == 'maintain':
            from .segments import process_one
            print(json.dumps(process_one(args.root)))
        elif args.command == 'restore-segments':
            from .segments import restore
            print(json.dumps(restore(args.root, args.output)))
        elif args.command == 'backtest':
            from .research import backtest
            cfg = Experiment(**json.loads(args.config.read_text())) if args.config else Experiment()
            print(backtest(args.db, args.output, cfg, args.split, args.unlock_holdout, args.end_id).resolve())
        elif args.command == 'demo':
            from .demo import create_demo
            from .research import backtest
            path = args.output / 'synthetic.sqlite3'
            create_demo(path)
            print(backtest(path, args.output, split='all', unlock_holdout=True).resolve())
        elif args.command == 'history':
            from .history import download
            print(json.dumps(asyncio.run(download(args.db, args.days, args.max_markets)), indent=2))
        elif args.command == 'screen':
            from .history import screen
            report = screen(args.db, args.output)
            print(json.dumps({k: v for k, v in report.items() if k != 'observations'}, indent=2))
        elif args.command in ('verify', 'backup'):
            from .storage import Store
            store = Store(args.db, readonly=True)
            try:
                result = store.backup(args.output) if args.command == 'backup' else store.verify()
                print(json.dumps(result, indent=2))
            finally:
                store.close()
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f'{type(exc).__name__}: {exc}\n')


if __name__ == '__main__':
    main()
