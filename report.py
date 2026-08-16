"""
Aggregate a run into the degradation curve.

    python3 report.py results/<file>.json [more.json ...]

The headline number is the derived per-step reliability p = success^(1/min_steps).
It is what lets you project how long a chain the model can sustain, instead of
arguing about it. Runs are grouped by band (v2) or by depth (v1).
"""

import json
import sys
from collections import Counter, defaultdict


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def report(summary: dict) -> None:
    runs = summary["runs"]
    groups = defaultdict(list)
    for r in runs:
        groups[r.get("band", f"d{r['depth']}")].append(r)

    print(f"\n=== {summary['model']}  [suite {summary.get('suite', 'v1')}] ===")
    print(f"{len(runs)} runs, {summary['reps']} reps/tache, {summary['wall_time_s']}s au total\n")

    print(f"{'bande':14} {'n':>4} {'succes':>8} {'p/etape':>8} {'etapes':>12} "
          f"{'leurres':>8} {'latence':>9}")
    print("-" * 70)

    per_step = {}
    for band in sorted(groups, key=lambda b: sum(r["min_steps"] for r in groups[b]) / len(groups[b])):
        rs = groups[band]
        n = len(rs)
        rate = sum(1 for r in rs if r["correct"]) / n
        mean_min = sum(r["min_steps"] for r in rs) / n
        mean_steps = sum(r["steps"] for r in rs) / n
        # Per-step reliability is derived from the calls actually executed, not
        # from the analytic minimum: it is the honest denominator.
        if rate > 0 and mean_steps > 0:
            p = rate ** (1.0 / mean_steps)
            per_step[band] = (p, mean_steps)
            p_txt = f"{p * 100:6.1f}%"
        else:
            p_txt = "     n/a"
        mean_decoy = sum(r.get("decoy_calls", 0) for r in rs) / n
        mean_lat = sum(r["latency_s"] for r in rs) / n
        print(f"{band:14} {n:4d} {rate * 100:7.1f}% {p_txt} "
              f"{mean_steps:5.1f}/{mean_min:<6.1f} {mean_decoy:7.1f} {mean_lat:8.1f}s")

    print("\nCauses d'arret (runs echoues) :")
    stops = Counter(r["stop_reason"] for r in runs if not r["correct"])
    for reason, count in stops.most_common():
        print(f"  {reason:16s} {count:3d}")
    if not stops:
        print("  aucune")

    errs = Counter(e for r in runs if not r["correct"] for e in r["errors"])
    if errs:
        print("\nSignaux d'outil sur les runs echoues :")
        for kind, count in errs.most_common():
            print(f"  {kind:18s} {count:3d}")

    # The projection models a chain that breaks one step at a time. v3 failures
    # are behavioural (a bare answer, an invented value, arithmetic drift over a
    # long context), not chain ruptures, so extrapolating from them would
    # produce a confident and meaningless number.
    if summary.get("suite") == "v3":
        print("\nPas de projection par etape sur cette suite : les echecs y sont "
              "comportementaux,\nnon des ruptures de chaine. La fiabilite par etape "
              "ne s'y interprete pas.")
    elif per_step:
        band = max(per_step, key=lambda b: per_step[b][1])
        p, mean_min = per_step[band]
        print(f"\nFiabilite par etape a la bande la plus profonde ({band}, "
              f"{mean_min:.0f} etapes) : {p * 100:.1f}%")
        print("Projection de succes bout-en-bout si elle reste constante :")
        for d in (5, 10, 20, 30, 50):
            print(f"  chaine de {d:2d} etapes -> {p ** d * 100:5.1f}%")
        for d in range(1, 200):
            if p ** d < 0.5:
                print(f"\nSeuil 50% de succes franchi a {d} etapes.")
                break

    failed = [r for r in runs if not r["correct"]]
    if failed:
        print(f"\n{len(failed)} echecs. Jusqu'a cinq exemples :")
        for r in failed[:5]:
            print(f"  {r['task_id']} rep{r['rep']}: attendu={r['expected']!r} "
                  f"obtenu={r['answer']!r} ({r['stop_reason']}, {r['steps']}/{r['min_steps']} etapes, "
                  f"{r.get('decoy_calls', 0)} leurres)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for path in sys.argv[1:]:
        report(load(path))
