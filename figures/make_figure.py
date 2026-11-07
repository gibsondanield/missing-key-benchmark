"""Figures for the blog: ns per operation against hit rate, one figure per task (10k operations).

    uv run python figures/make_figure.py      # writes figures/hit_rate_{count,group,memo}.{svg,png}

Dark theme to match the blog's black background. The categorical colours are the dataviz
reference dark steps (8 slots), validated against #000 (all checks pass); each strategy keeps
its colour and marker in every figure, and markers act as a second encoding.
"""
import sys
from pathlib import Path

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from report import load  # noqa: E402

N = 10_000
SURFACE, INK, INK2, MUTED, GRID = '#000000', '#f0efec', '#c3c2b7', '#898781', '#2c2c2a'

STYLE = {
    'in_check':        ('if k in d',        '#3987e5', 'o'),
    'get':             ('d.get',            '#d95926', 's'),
    'try_except':      ('try / except',     '#199e70', 'D'),
    'defaultdict':     ('defaultdict',      '#c98500', '^'),
    'setdefault':      ('d.setdefault',     '#d55181', 'v'),
    'Counter':         ('Counter',          '#008300', 'p'),
    '__missing__':     ('subclass with __missing__', '#9085e9', 'h'),
    'functools.cache': ('functools.cache',  '#e66767', '*'),
}
FIGURES = [
    ('count', 'Counting:  d[k] += 1', ['in_check', 'get', 'try_except', 'defaultdict', 'Counter']),
    ('group', 'Grouping:  d[k].append(v)', ['in_check', 'setdefault', 'try_except', 'defaultdict']),
    ('memo', 'Memoizing:  v = f(k), at most once per key',
     ['in_check', 'try_except', 'setdefault', '__missing__', 'functools.cache']),
]

df = load()
df = df[df.n == N]
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11, 'text.color': INK,
                     'axes.labelcolor': INK2, 'xtick.color': INK2, 'ytick.color': INK2})

for workload, title, strategies in FIGURES:
    fig, ax = plt.subplots(figsize=(7, 4.4), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    for s in strategies:
        label, color, marker = STYLE[s]
        g = df[(df.workload == workload) & (df.strategy == s)].sort_values('hit_rate')
        ax.plot(g.hit_rate * 100, g.ns, color=color, lw=2, marker=marker, ms=8 if marker == '*' else 7,
                markeredgecolor=SURFACE, markeredgewidth=1.2, label=label)
    if workload == 'memo':  # reference: calling f every time
        g = df[(df.workload == 'memo') & (df.strategy == 'no_cache')].sort_values('hit_rate')
        ax.plot(g.hit_rate * 100, g.ns, color=MUTED, lw=1.5, ls='--', label='no cache (f every time)')
    ax.set_title(title, loc='left', fontsize=13, color=INK, pad=10)
    ax.set_xlabel('keys already in the dict (%)')
    ax.set_ylabel('ns per operation')
    ax.set_xticks([0, 25, 50, 75, 90, 100])
    ax.set_ylim(0, df[df.workload == workload].ns.max() * 1.1)
    ax.grid(axis='y', color=GRID, lw=1)
    for side in ('top', 'right', 'left'):
        ax.spines[side].set_visible(False)
    ax.spines['bottom'].set_color(GRID)
    ax.tick_params(length=0)
    ax.legend(frameon=False, loc='upper right', labelcolor=INK2, fontsize=10)
    fig.text(0.01, 0.01, f'CPython 3.14, {N:,} operations, median of 7+ runs, empty-loop cost subtracted',
             color=MUTED, fontsize=8.5)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    out = Path(__file__).parent / f'hit_rate_{workload}.svg'
    fig.savefig(out, facecolor=SURFACE)
    fig.savefig(out.with_suffix('.png'), facecolor=SURFACE, dpi=150)
    plt.close(fig)
    print('wrote', out)
