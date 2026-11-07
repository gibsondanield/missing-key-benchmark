"""Print the benchmark results in results/*.csv as tables.

    uv run python report.py

Times are ns per operation. For per-item strategies the empty-loop cost from the same run and
hit rate is subtracted; bulk strategies have no Python loop, so they are left as measured.
"""
from pathlib import Path

import pandas as pd


def load():
    df = pd.concat([pd.read_csv(p) for p in sorted(Path(__file__).parent.glob('results/*.csv'))])
    key = ['python', 'n', 'hit_rate']
    base = df[df.workload == 'baseline'].set_index(key).ns_per_op.rename('loop_ns')
    df = df[df.workload != 'baseline'].join(base, on=key)
    df['ns'] = df.ns_per_op - df.loop_ns.where(~df.bulk, 0)
    df['label'] = df.strategy.where(df.workload != 'control', df.strategy + ' on ' + df.container)
    return df


def main():
    df = load()
    pd.set_option('display.width', 200)
    for (python, n, workload), g in df.groupby(['python', 'n', 'workload'], sort=False):
        table = g.pivot(index='label', columns='hit_rate', values='ns').round(1)
        print(f'\n{workload}, {python}, n={n:,}: ns/op by hit rate')
        print(table.sort_values(table.columns[-2]))


if __name__ == '__main__':
    main()
