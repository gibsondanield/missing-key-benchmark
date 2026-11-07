# Missing-key benchmark: get, setdefault, try/except, defaultdict, Counter

Code for the blog post [Missing keys: a benchmark](https://gibsondanield.github.io/blog/missing_keys/).

How fast are the usual ways of updating a dict entry that may not exist yet, and when does each one win?
Every strategy is timed as an inline statement (no wrapper function), on pre-generated string keys,
across a sweep of *hit rates*: the fraction of operations whose key is already in the dict.

## Results (CPython 3.14, 10,000 operations, ns per operation)

Three tasks: counting (`d[k] += 1`), grouping (append to a list at `d[k]`) and memoizing
(compute `f(k)` at most once per key). Counting:

| strategy | 0% hits | 50% | 90% | 100% |
|---|---|---|---|---|
| `Counter.update(keys)` (bulk) | 17.3 | 18.0 | 13.3 | 11.7 |
| `if k in d` | 23.7 | 26.6 | 21.6 | 21.4 |
| `d[k] = d.get(k, 0) + 1` | 27.1 | 25.5 | 18.4 | 17.5 |
| `defaultdict(int)` | 44.6 | 34.4 | 21.4 | 17.4 |
| `try` / `except KeyError` | 72.0 | 46.8 | 22.9 | 16.0 |
| `Counter()`, `d[k] += 1` | 63.3 | 52.5 | 40.7 | 36.8 |

Memoizing: `d.setdefault(k, f(k))` is slower than not caching at all, because `f(k)` is evaluated
on every call. Full tables for every task, plus a 1M-operation run where the dict outgrows the CPU
cache, are in `results/`; `uv run python report.py` prints them.

## Running

Requires [uv](https://docs.astral.sh/uv/). `bench.py` uses only the standard library, so it runs on any Python.

```
uv sync
uv run python bench.py -n 10000      # fits in CPU cache
uv run python bench.py               # 1M operations: the dict outgrows the cache
uv run python report.py
uv run python figures/make_figure.py
uv run --no-project --python 3.13 python bench.py   # another interpreter
```

## License

MIT
