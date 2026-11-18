"""Charts for docs/RESULTS_*.md (static PNG; the doc carries the same numbers as tables).

python eval/charts.py v0 -> docs/img/v0_arms.png, v0_ltr.png, v0_judge_sources.png
python eval/charts.py v1 -> docs/img/v1_arms.png, v1_ltr.png (orderings fitted on v0, applied to the v1 pool)
python eval/charts.py v2 -> docs/img/v2_arms.png (no pool-reordering chart: v2 has none)
python eval/charts.py coverage v1 v1b -> docs/img/coverage_v1_v1b.png (arm F, old vs new corpus, eval/coverage.py)
python eval/charts.py coverage v2o v2 -> docs/img/coverage_v2o_v2.png
python eval/charts.py coverage v3o v3 J -> docs/img/coverage_v3o_v3.png (arm J instead of F)
python eval/charts.py v3split -> docs/img/v3_by_best.png (eval/report_v3.py: arms with and without a good posting)
python eval/charts.py curve -> docs/img/v3_learning_curve.png (eval/model_checks.py: L's recipe on more and more queries)
python eval/charts.py ablate -> docs/img/ablate_hand.png (eval/ablate_hand.py: each hand term added to rerank only)
python eval/charts.py gaps -> docs/img/gaps_by_category.png (eval/gaps.py: held-out queries with a rel >= 2 posting)
Palette: reference categorical slots 1-3 (blue, orange, aqua) on the light chart surface.
"""
import json
import sqlite3
import sys
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval import score  # noqa: E402

SURFACE, INK, INK2, GRID = '#fcfcfb', '#0b0b0b', '#52514e', '#e4e3df'
SERIES = ['#2a78d6', '#eb6834', '#1baf7a']
LANGS = [('zh', 'Chinese'), ('en', 'English'), ('mix', 'Mixed zh-en')]
for _f in ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc'):
    if Path(_f).exists():  # .ttc is not picked up by matplotlib's font scan; register it so CJK labels render
        font_manager.fontManager.addfont(_f)
plt.rcParams.update({'font.family': ['Noto Sans CJK JP', 'DejaVu Sans'], 'font.size': 10,
                     'axes.edgecolor': GRID, 'axes.labelcolor': INK2, 'xtick.color': INK2, 'ytick.color': INK2,
                     'text.color': INK, 'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE})


def _frame(ax, title, ylabel):
    ax.set_title(title, loc='left', fontsize=12, color=INK, pad=12)
    ax.set_ylabel(ylabel)
    ax.grid(axis='y', color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ('top', 'right', 'left'):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)


def grouped(ax, groups, series_vals, labels, width=0.24):
    n = len(series_vals)
    for k, (vals, lab) in enumerate(zip(series_vals, labels)):
        xs = [i + (k - (n - 1) / 2) * width for i in range(len(groups))]
        ax.bar(xs, vals, width=width, color=SERIES[k], label=lab, edgecolor=SURFACE, linewidth=2)
    ax.set_xticks(range(len(groups)), groups)
    ax.legend(frameon=False, ncol=n, loc='upper left', bbox_to_anchor=(0, 1.02))


def main(name: str):
    held_out = name != 'v0'

    out = ROOT / 'docs' / 'img'
    out.mkdir(parents=True, exist_ok=True)
    table = score.main(name)
    arms = [r['arm'] for r in table]
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    grouped(ax, arms, [[r[f'nDCG {lg}'] for r in table] for lg, _ in LANGS], [l for _, l in LANGS])
    nq = table[0]['queries']
    _frame(ax, f'nDCG@10 by arm and query language ({nq} answerable {"held-out " if held_out else ""}queries)', 'nDCG@10')
    ax.set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(out / f'{name}_arms.png', facecolor=SURFACE)

    ltr_f = ROOT / 'eval' / (f'ltr_{name}_from_v0.json' if held_out else f'ltr_{name}.json')
    if not ltr_f.exists():
        print('charts ->', out)
        return
    ltr = json.loads(ltr_f.read_text())
    keys = list(ltr)
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    short = {'hand_G': 'hand\nweights', 'gbm -ai_judge': 'gbm\n−judge', 'gbm -ai_rewrite': 'gbm\n−rewrite',
             'gbm -both': 'gbm\n−both'}
    grouped(ax, [short.get(k, k) for k in keys],
            [[ltr[k][lg]['nDCG@10'] for k in keys] for lg, _ in LANGS], [l for _, l in LANGS])
    _frame(ax, 'Reordering the labeled held-out pool, fitted on v0' if held_out else
           'Reordering the labeled pool: leave-one-query-out nDCG@10', 'nDCG@10')
    ax.set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(out / f'{name}_ltr.png', facecolor=SURFACE)
    if held_out:  # the judge chart covers the whole database, drawn with v0
        print('charts ->', out)
        return

    c = sqlite3.connect(ROOT / 'data' / 'rankai.sqlite')
    rows = c.execute("select o.source, sum(j.scores like '%\"is_opportunity\": false%'), count(*) from judgments j "
                     "join opps o on o.id=j.opp_id where j.kind='posting' group by o.source").fetchall()
    rows = sorted(rows, key=lambda r: r[1] / r[2])
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    ax.barh([f'{s} (n={n})' for s, _, n in rows], [k / n for _, k, n in rows], color=SERIES[0], height=0.6,
            edgecolor=SURFACE, linewidth=2)
    for i, (_, k, n) in enumerate(rows):
        if k:
            ax.text(k / n + 0.01, i, f'{k / n:.0%}', va='center', color=INK2, fontsize=9)
    _frame(ax, 'AI posting judge: share judged "not an opportunity", by source', '')
    ax.grid(axis='x', color=GRID, linewidth=0.8)
    ax.grid(axis='y', visible=False)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    fig.tight_layout()
    fig.savefig(out / f'{name}_judge_sources.png', facecolor=SURFACE)
    print('charts ->', out)


def coverage(old: str, new: str, arm: str = 'F'):
    rep = json.loads((ROOT / 'eval' / f'coverage_{old}_{new}.json').read_text())[arm]
    c = sqlite3.connect(ROOT / 'data' / 'rankai.sqlite')
    n_old, n_new = (c.execute('select n from snapshots where name=?', (x,)).fetchone()[0] for x in (old, new))
    qset = old.removesuffix('o')  # v1 / v1b and v2o / v2 share their queries
    groups = [('all', 'all 48'), ('zh', 'Chinese'), ('en', 'English'), ('mix', 'Mixed zh-en')]
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    grouped(ax, [g for _, g in groups], [[rep[side][k]['P@5'] for k, _ in groups] for side in ('old', 'new')],
            [f'before ({n_old:,} postings)', f'after ({n_new:,} postings)'], width=0.32)
    for i, (k, _) in enumerate(groups):
        for j, side in enumerate(('old', 'new')):
            r = rep[side][k]
            ax.text(i + (j - 0.5) * 0.32, r['P@5'] + 0.01, f"{r['covered']}/{r['queries']}", ha='center',
                    va='bottom', fontsize=8, color=INK2)
    _frame(ax, f'Arm {arm} on the {qset} queries: P@5 before / after new sources (x/y = queries with a good result)',
           'P@5 (rel ≥ 2)')
    ax.set_ylim(0, max(0.3, 1.4 * max(rep[s][k]['P@5'] for s in ('old', 'new') for k, _ in groups)))
    fig.tight_layout()
    out = ROOT / 'docs' / 'img' / f'coverage_{old}_{new}.png'
    fig.savefig(out, facecolor=SURFACE)
    print('chart ->', out)


def v3split():
    rep = json.loads((ROOT / 'eval' / 'report_v3.json').read_text())['by_best']
    fig, axes = plt.subplots(1, 2, figsize=(8, 4.2), dpi=150, sharey=True)
    for ax, key, what in ((axes[0], 'best_ge2', 'a good posting exists'), (axes[1], 'best_below2', 'no good posting')):
        vals = [rep[key][a] for a in 'FJLM']
        ax.bar(list('FJLM'), vals, width=0.6, color=SERIES[0], edgecolor=SURFACE, linewidth=2)
        for i, v in enumerate(vals):
            ax.text(i, v + 0.015, f'{v:.3f}', ha='center', fontsize=9, color=INK2)
        _frame(ax, f"{what} ({rep[key]['queries']} queries)", '')
    axes[0].set_ylabel('nDCG@10')
    axes[0].set_ylim(0, 1)
    fig.suptitle('v3: J beats F only where nothing good exists', x=0.02, ha='left', fontsize=13, color=INK)
    fig.tight_layout()
    out = ROOT / 'docs' / 'img' / 'v3_by_best.png'
    fig.savefig(out, facecolor=SURFACE)
    print('chart ->', out)


def curve():
    rep = json.loads((ROOT / 'eval' / 'model_checks_v3.json').read_text())
    xs = [int(n) for n in rep['curve']]
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    ax.fill_between(xs, [v['min'] for v in rep['curve'].values()], [v['max'] for v in rep['curve'].values()],
                    color=SERIES[0], alpha=0.15, linewidth=0, label='range over 20 random subsets')
    ax.plot(xs, [v['mean'] for v in rep['curve'].values()], color=SERIES[0], linewidth=2, marker='o', markersize=6,
            label="L's recipe, mean")
    rerank = rep['saved']['rerank only']
    ax.axhline(rerank, color=INK2, linewidth=1.2, linestyle='--', label=f'reranker score only ({rerank:.3f})')
    _frame(ax, 'More labeled queries, better order on the v3 held-out pool', 'nDCG@10')
    ax.set_xlabel('training queries')
    ax.set_xticks(xs)
    ax.set_ylim(0.70, 0.82)
    ax.legend(frameon=False, loc='lower right')
    fig.tight_layout()
    out = ROOT / 'docs' / 'img' / 'v3_learning_curve.png'
    fig.savefig(out, facecolor=SURFACE)
    print('chart ->', out)


def ablate():
    rep = json.loads((ROOT / 'eval' / 'ablate_hand.json').read_text())
    rows = [('F (all terms)', 'F: all terms'),
            ('rerank + engagement-type violation only', '+ engagement-type penalty'),
            ('rerank + completeness only', '+ completeness bonus'),
            ('rerank + freshness only', '+ freshness bonus'),
            ('rerank + scam rule only', '+ scam-rule penalty'),
            ('rerank + source trust only', '+ source-trust bonus'),
            ('rerank + remote violation only', '+ remote penalty'),
            ('rerank + pay violation only', '+ pay penalty'),
            ('rerank x (1 - 0.5 x violations)', 'penalties as a multiplier')]
    series = [('v1+v2', 'held-out v1 + v2 (90 queries)'), ('v0', 'v0 (48 tech-leaning queries)')]
    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=150)
    h = 0.36
    for k, (name, lab) in enumerate(series):
        vals = [rep[name]['orderings'][r]['vs rerank only (J)']['diff'] for r, _ in rows]
        ys = [i + (k - 0.5) * h for i in range(len(rows))]
        ax.barh(ys, vals, height=h, color=SERIES[k], label=lab, edgecolor=SURFACE, linewidth=2)
        if name == 'v1+v2':
            for y, (r, _), v in zip(ys, rows, vals):
                pv = rep[name]['orderings'][r]['vs rerank only (J)']['p']
                ax.text(v - 0.002 if v < 0 else v + 0.002, y, 'p<0.001' if pv < 0.001 else f'p={pv:.2f}',
                        ha='right' if v < 0 else 'left', va='center', fontsize=8, color=INK2)
    ax.set_yticks(range(len(rows)), [l for _, l in rows])
    ax.invert_yaxis()
    ax.axvline(0, color=INK2, linewidth=1)
    ax.set_xlim(-0.085, 0.04)
    _frame(ax, 'Change in nDCG@10 vs rerank only (J) when one hand-set term is added', '')
    ax.grid(axis='x', color=GRID, linewidth=0.8)
    ax.grid(axis='y', visible=False)
    ax.legend(frameon=False, ncol=2, loc='upper center', bbox_to_anchor=(0.35, -0.07), fontsize=9)
    fig.tight_layout()
    out = ROOT / 'docs' / 'img' / 'ablate_hand.png'
    fig.savefig(out, facecolor=SURFACE)
    print('chart ->', out)


def gaps():
    rep = json.loads((ROOT / 'eval' / 'gaps.json').read_text())
    names = {'local': 'local, on-site (a city named)', 'project outsourcing': 'project outsourcing (buyer side)',
             'co-founder': 'co-founder', 'bounty': 'open-source bounty', 'remote, other': 'remote roles'}
    cats = list(rep['by_category'])
    cov = [rep['by_category'][c]['covered'] for c in cats]
    gap = [rep['by_category'][c]['queries'] - rep['by_category'][c]['covered'] for c in cats]
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=150)
    ax.barh(range(len(cats)), cov, height=0.6, color=SERIES[0], label='has a good posting (rel >= 2)',
            edgecolor=SURFACE, linewidth=2)
    ax.barh(range(len(cats)), gap, left=cov, height=0.6, color=SERIES[1], label='no good posting in the pool',
            edgecolor=SURFACE, linewidth=2)
    for i, (a, b) in enumerate(zip(cov, gap)):
        for x, w in ((0, a), (a, b)):
            if w:
                ax.text(x + w / 2, i, str(w), ha='center', va='center', fontsize=9, color='white')
        ax.text(a + b + 0.6, i, f'{a}/{a + b} covered', va='center', fontsize=9, color=INK2)
    ax.set_yticks(range(len(cats)), [names[c] for c in cats])
    ax.invert_yaxis()
    ax.set_xlim(0, max(a + b for a, b in zip(cov, gap)) + 9)
    _frame(ax, f"Held-out queries (v1 + v2) by type: {rep['covered']}/{rep['queries']} have a good posting", '')
    ax.grid(axis='x', color=GRID, linewidth=0.8)
    ax.grid(axis='y', visible=False)
    ax.set_xlabel('queries')
    ax.legend(frameon=False, ncol=2, loc='upper center', bbox_to_anchor=(0.4, -0.18), fontsize=9)
    fig.tight_layout()
    out = ROOT / 'docs' / 'img' / 'gaps_by_category.png'
    fig.savefig(out, facecolor=SURFACE)
    print('chart ->', out)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'ablate':
        ablate()
    elif len(sys.argv) > 1 and sys.argv[1] == 'curve':
        curve()
    elif len(sys.argv) > 1 and sys.argv[1] == 'v3split':
        v3split()
    elif len(sys.argv) > 1 and sys.argv[1] == 'gaps':
        gaps()
    elif len(sys.argv) > 1 and sys.argv[1] == 'coverage':
        coverage(*sys.argv[2:5])
    else:
        main(sys.argv[1] if len(sys.argv) > 1 else 'v0')
