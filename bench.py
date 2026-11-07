"""Benchmark the ways of updating a dict entry that may not exist yet.

Standard library only, so it runs unchanged on any Python version:

    uv run python bench.py                  # 1M operations: the dict outgrows CPU cache
    uv run python bench.py -n 10000         # 10k operations: everything stays in cache

Each run writes results/<implementation>-<version>-n<n>.csv; report.py summarises them.

Method:
- Each strategy is an inline statement timed with timeit, so there is no extra function
  call per operation. The cost of an empty loop is measured too and subtracted in report.py.
- Keys are strings (like word counting) and are generated before timing starts.
- hit_rate is the fraction of operations whose key is already in the dict. Hits pick a key
  uniformly from those inserted so far. Note that it also sets the final dict size:
  n * (1 - hit_rate) entries.
- Every repeat starts from a fresh container, built outside the timed region. The median
  is reported.
- "bulk" strategies hand the whole key list to one call instead of looping in Python.
"""
import argparse
import csv
import platform
import random
import statistics
import sys
import timeit
from collections import Counter, defaultdict
from functools import cache
from pathlib import Path


def f(k):
    '''The "expensive" computation being memoized: a few hundred ns, deterministic.'''
    return sum(map(ord, k))


class ZeroDict(dict):
    '''Like Counter's lookup: a missing key reads as 0 but is not inserted.'''
    def __missing__(self, k):
        return 0


class ListDict(dict):
    '''Like defaultdict(list), written in Python: a missing key gets a new list, inserted.'''
    def __missing__(self, k):
        v = self[k] = []
        return v


class MemoDict(dict):
    '''A missing key is computed from the key itself, which defaultdict cannot do.'''
    def __missing__(self, k):
        v = self[k] = f(k)
        return v


# Containers: setup code, run untimed before each repeat. `keys` is the key list.
CONTAINERS = {
    'dict': 'd = {}',
    'defaultdict(int)': 'd = defaultdict(int)',
    'defaultdict(list)': 'd = defaultdict(list)',
    'Counter': 'd = Counter()',
    'ZeroDict': 'd = ZeroDict()',
    'ListDict': 'd = ListDict()',
    'prefilled 0': 'd = dict.fromkeys(set(keys), 0)',
    'prefilled []': 'd = {k: [] for k in set(keys)}',
    'MemoDict': 'd = MemoDict()',
    'functools.cache': 'd = cache(f)',
}

# (workload, strategy, container, statement, bulk)
# "count": d[k] += 1.   "group": append to the list stored at d[k].
# "memo": v = f(k), computing f at most once per key (the default depends on the key).
STRATEGIES = [
    ('count', 'try_except',   'dict', 'try:\n    d[k] += 1\nexcept KeyError:\n    d[k] = 1', False),
    ('count', 'in_check',     'dict', 'if k in d:\n    d[k] += 1\nelse:\n    d[k] = 1', False),
    ('count', 'get',          'dict', 'd[k] = d.get(k, 0) + 1', False),
    ('count', 'setdefault',   'dict', 'd[k] = d.setdefault(k, 0) + 1', False),
    ('count', 'walrus',       'dict', 'd[k] = 1 if (c := d.get(k)) is None else c + 1', False),
    ('count', 'defaultdict',  'defaultdict(int)', 'd[k] += 1', False),
    ('count', '__missing__',  'ZeroDict', 'd[k] += 1', False),
    ('count', 'Counter',      'Counter', 'd[k] += 1', False),
    ('count', 'prefilled',    'prefilled 0', 'd[k] += 1', False),
    ('count', 'Counter.update (bulk)', 'Counter', 'd.update(keys)', True),

    ('group', 'try_except',   'dict', 'try:\n    d[k].append(1)\nexcept KeyError:\n    d[k] = [1]', False),
    ('group', 'in_check',     'dict', 'if k in d:\n    d[k].append(1)\nelse:\n    d[k] = [1]', False),
    ('group', 'setdefault',   'dict', 'd.setdefault(k, []).append(1)', False),
    ('group', 'get_or_setdefault', 'dict', '(d.get(k) or d.setdefault(k, [])).append(1)', False),
    ('group', 'walrus',       'dict', 'if (v := d.get(k)) is None:\n    d[k] = v = []\nv.append(1)', False),
    ('group', 'defaultdict',  'defaultdict(list)', 'd[k].append(1)', False),
    ('group', '__missing__',  'ListDict', 'd[k].append(1)', False),
    ('group', 'prefilled',    'prefilled []', 'd[k].append(1)', False),

    ('memo', 'try_except',    'dict', 'try:\n    v = d[k]\nexcept KeyError:\n    v = d[k] = f(k)', False),
    ('memo', 'in_check',      'dict', 'if k in d:\n    v = d[k]\nelse:\n    v = d[k] = f(k)', False),
    ('memo', 'walrus',        'dict', 'if (v := d.get(k)) is None:\n    v = d[k] = f(k)', False),
    ('memo', 'setdefault',    'dict', 'v = d.setdefault(k, f(k))', False),
    ('memo', '__missing__',   'MemoDict', 'v = d[k]', False),
    ('memo', 'functools.cache', 'functools.cache', 'v = d(k)', False),
    ('memo', 'no_cache',      'dict', 'v = f(k)', False),

    # Controls: plain-dict code run on the subclasses, to isolate the subclass overhead.
    ('control', 'get', 'defaultdict(int)', 'd[k] = d.get(k, 0) + 1', False),
    ('control', 'get', 'Counter', 'd[k] = d.get(k, 0) + 1', False),
    ('control', 'get', 'ZeroDict', 'd[k] = d.get(k, 0) + 1', False),

    ('baseline', 'empty_loop', 'dict', 'pass', False),
]

HIT_RATES = (0.0, 0.25, 0.5, 0.75, 0.9, 0.99, 1.0)


def make_keys(n, hit_rate, seed=0):
    '''n string keys; each is a repeat of an earlier key with probability hit_rate.'''
    rng = random.Random(seed)
    seen, keys = [], []
    for _ in range(n):
        if seen and rng.random() < hit_rate:
            keys.append(rng.choice(seen))
        else:
            seen.append(f'key{len(seen)}')
            keys.append(seen[-1])
    return keys


def time_strategy(stmt, container, keys, repeat, bulk):
    if not bulk:
        stmt = 'for k in keys:\n' + '\n'.join('    ' + line for line in stmt.splitlines())
    timer = timeit.Timer(stmt, setup=CONTAINERS[container],
                         globals={'keys': keys, 'defaultdict': defaultdict, 'Counter': Counter,
                                  'ZeroDict': ZeroDict, 'ListDict': ListDict, 'MemoDict': MemoDict,
                                  'cache': cache, 'f': f})
    return statistics.median(timer.repeat(repeat=repeat, number=1)) / len(keys) * 1e9


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-n', type=int, default=1_000_000, help='operations per timing')
    parser.add_argument('--repeat', type=int, help='timings per point (default: more for small n)')
    args = parser.parse_args()
    repeat = args.repeat or min(101, max(7, 10_000_000 // args.n))

    version = f'{platform.python_implementation()}-{platform.python_version()}'
    jit = getattr(getattr(sys, '_jit', None), 'is_enabled', lambda: False)()
    out = Path(__file__).parent / 'results' / f'{version}{"-jit" if jit else ""}-n{args.n}.csv'
    out.parent.mkdir(exist_ok=True)

    rows = []
    for hit_rate in HIT_RATES:
        keys = make_keys(args.n, hit_rate)
        for workload, name, container, stmt, bulk in STRATEGIES:
            ns = time_strategy(stmt, container, keys, repeat, bulk)
            rows.append(dict(python=version, jit=jit, n=args.n, workload=workload, strategy=name,
                             container=container, bulk=bulk, hit_rate=hit_rate, ns_per_op=round(ns, 2)))
        print(f'{version} n={args.n}: hit rate {hit_rate:.2f} done', flush=True)

    with out.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=rows[0], lineterminator='\n')
        w.writeheader()
        w.writerows(rows)
    print(f'wrote {out}', flush=True)


if __name__ == '__main__':
    main()
