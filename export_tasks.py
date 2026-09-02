#!/usr/bin/env python3
"""Exporte les tâches des trois suites en JSON, pour qui publie les résultats.

Les résultats (results/*.json) et les traces (traces/*.jsonl) portent l'identifiant
de chaque tâche, sa bande et la réponse attendue, mais pas la question posée au
modèle : elle n'existe que dans tasks*.py, reconstruite depuis la graine du monde.
La vitrine, qui monte ce dépôt en lecture seule, a besoin de la question pour
montrer une chaîne d'appels de façon compréhensible. D'où ce fichier par suite,
généré ici (le projet produit, la vitrine publie) et versionné avec les résultats.

    python3 export_tasks.py      # écrit tasks/v1.json, tasks/v2.json, tasks/v3.json
"""

import json
import os

from runner import load_suite

KEEP = ("id", "band", "depth", "min_steps", "question", "scoring", "kind",
        "expected", "variants", "conflit_valeurs")


def main() -> None:
    base = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(base, "tasks")
    os.makedirs(out_dir, exist_ok=True)
    for suite in ("v1", "v2", "v3"):
        tasks, *_ = load_suite(suite)
        rows = [{k: t[k] for k in KEEP if k in t} for t in tasks]
        path = os.path.join(out_dir, f"{suite}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"suite": suite, "tasks": rows}, fh, ensure_ascii=False, indent=1)
        print(f"{path}: {len(rows)} tâches")


if __name__ == "__main__":
    main()
