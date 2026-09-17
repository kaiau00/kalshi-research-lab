"""JSON-only object graph codec for exact resumable simulator state (no pickle)."""
from collections import deque
from decimal import Decimal

from .engine import Account, Replay
from .market import Book, MarketState
from .settings import Experiment

TYPES = {c.__name__: c for c in (Account, Replay, Book, MarketState, Experiment)}


def encode(root):
    memo = {}

    def visit(v):
        if v is None or isinstance(v, (str, int, float, bool)):
            return v
        if isinstance(v, Decimal):
            return {'type': 'decimal', 'value': str(v)}
        if id(v) in memo:
            return {'ref': memo[id(v)]}
        key = len(memo)
        memo[id(v)] = key
        if isinstance(v, dict):
            typ, data = 'dict', [[visit(k), visit(x)] for k, x in v.items()]
        elif isinstance(v, (list, tuple, set, deque)):
            typ, data = type(v).__name__, [visit(x) for x in v]
        elif type(v).__name__ in TYPES and type(v) is TYPES[type(v).__name__]:
            typ, data = type(v).__name__, visit(vars(v))
        else:
            raise ValueError('Unsupported checkpoint type')
        return {'id': key, 'type': typ, 'value': data}
    return visit(root)


def decode(root):
    memo = {}

    def visit(v):
        if not isinstance(v, dict):
            return v
        if 'ref' in v:
            return memo[v['ref']]
        typ, data = v['type'], v['value']
        if typ == 'decimal':
            return Decimal(data)
        if typ == 'dict':
            out = {}
            memo[v['id']] = out
            out.update((visit(k), visit(x)) for k, x in data)
        elif typ in ('list', 'tuple', 'set', 'deque'):
            items = [visit(x) for x in data]
            out = {'list': list, 'tuple': tuple, 'set': set, 'deque': lambda x: deque(x, maxlen=7200)}[typ](items)
        elif typ in TYPES:
            out = TYPES[typ].__new__(TYPES[typ])
            memo[v['id']] = out
            for k, x in visit(data).items():
                object.__setattr__(out, k, x)
        else:
            raise ValueError('Unsupported checkpoint tag')
        memo[v['id']] = out
        return out
    return visit(root)
