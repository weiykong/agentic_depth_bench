# agentic_depth_bench

Mesure jusqu'à quelle **profondeur de chaîne d'appels d'outils** un modèle local
tient, sur un monde déterministe dont la vérité terrain est calculée en Python
indépendamment du chemin pris par le modèle.

Objectif : remplacer l'opinion (« les petits modèles ne tiennent pas l'agentique »)
par une courbe mesurée sur *notre* matériel et *nos* modèles.

Modèle testé : `gemma-4-12b-it-w4a16` (Gemma 4 12B QAT W4A16, vLLM,
`--tool-call-parser gemma4`), sur RTX PRO 4000 Blackwell 24 Go.

---

## Suite v1 — enchaînement guidé (2026-08-15)

Chaîne linéaire, 7 outils sans leurre, chemin énoncé par la question.

| Profondeur | n | Succès | Étapes moy. / min | Latence |
|---|---|---|---|---|
| 1 | 15 | 100 % | 1,0 / 1 | 1,1 s |
| 3 | 15 | 100 % | 3,0 / 3 | 2,2 s |
| 6 | 15 | 100 % | 6,0 / 6 | 3,7 s |
| 10 | 15 | 100 % | 10,0 / 10 | 6,5 s |

60/60, 300 appels d'outils, 0 erreur, chemin optimal systématique.

## Suite v2 — les six pressions (2026-08-16)

24 outils dont 11 leurres, chemin non énoncé, branchement conditionnel, outil
qui échoue volontairement, agrégat périmé qui inverse la branche s'il est cru.

| Bande | n | Succès | Étapes moy. / min | Leurres | Latence |
|---|---|---|---|---|---|
| A_selection | 15 | 100 % | 4,6 / 3,0 | 0,0 | 3,5 s |
| B_branching | 15 | 100 % | 7,6 / 6,6 | 0,0 | 4,5 s |
| C_recovery | 15 | 100 % | 10,8 / 10,0 | 0,0 | 7,3 s |
| D_composite | 15 | 100 % | 19,0 / 18,0 | 0,0 | 13,7 s |

60/60 à nouveau. Vérifications que les pressions ont bien mordu :

- **Récupération d'erreur** : 120 échecs de `get_tarif_negocie`, repli sur le
  prix catalogue correct 120 fois sur 120.
- **Distracteur** : 60 appels `get_stock_entrepot` (4 entrepôts × 15 runs,
  le compte exact), **0 appel** à `get_stock_global` — l'agrégat périmé était
  pourtant construit pour inverser la branche dans les 5 cas.
- **Sélection** : 15 outils sur 24 jamais appelés, dont la totalité des leurres.
- **Branchement** : les deux sens de la condition sont couverts (3 instances
  sous le seuil, 2 au-dessus) et tranchés correctement.

## Ce que ces deux runs établissent

La mécanique agentique est **acquise** à 12B sur des tâches bien spécifiées :
enchaînement à 19 étapes, sélection parmi 24 outils, branchement conditionnel,
récupération d'erreur, résistance à un distracteur construit pour tromper.

Borne de confiance : avec 15/15 sur la bande D, la borne basse à 95 %
(Clopper-Pearson) sur le succès bout-en-bout est 81,9 %, soit une fiabilité
**par étape ≥ 98,9 %** sur 19 étapes réellement exécutées.

L'hypothèse de départ — ~90 % par étape, donc effondrement à 35 % sur 10 étapes —
est réfutée. Elle ne l'est pas « un peu » : elle est fausse d'un ordre de grandeur
sur le taux d'échec.

## Ce que ces runs n'établissent PAS

Toutes les tâches **énoncent la règle**. « Applique le tarif négocié s'il existe,
sinon le prix catalogue » est une spécification complète : le modèle exécute, il
ne décide pas. Ne sont toujours pas testés :

- l'**intention sous-spécifiée** — l'utilisateur ne dit pas la règle, il dit
  « combien nous a rapporté ce magasin ? » et la règle de prix est à inférer ;
- le **jugement** — aucune de ces tâches n'a de réponse discutable ;
- les **données contradictoires** — ici une seule source fait autorité ;
- le **contexte long** — quelques Ko sur les 131 k disponibles ;
- les **actions irréversibles** — tous les outils sont en lecture ;
- la **variance** — température 0, 3 répétitions strictement identiques.

Quatre scores parfaits d'affilée à difficulté croissante veulent dire que le
plafond n'est pas atteint, pas qu'il n'existe pas.

## Bug de plateforme trouvé au passage

**Tous les runs** contiennent des tokens de template dans le champ `content` :

```
<|channel>thought\n<channel|>REPONSE: 4671.99
```

Le parser `gemma4` de vLLM ne nettoie pas les marqueurs de canal de réflexion.
Toute application agentique bâtie sur cet endpoint recevra ces tokens et devra
les filtrer. C'est ce qui a fait échouer le premier smoke test : le modèle avait
la bonne réponse, le scoring l'a comptée fausse. Sans ce test unitaire, ce banc
publiait une courbe d'effondrement entièrement fabriquée.

`runner.py` les neutralise via `_CTRL_TOKEN_RE`. À corriger en amont côté vLLM.

## Utilisation

```bash
export VLLM_API_KEY=$(docker inspect sc-inference-vllm-1 \
  --format '{{range .Config.Env}}{{println .}}{{end}}' | grep VLLM_API_KEY | cut -d= -f2)
python3 runner.py --suite v2 --reps 3 --tag full
```

Aucune dépendance : bibliothèque standard uniquement (Python 3.14 sur sc-lab).

| Option | Effet |
|---|---|
| `--suite v1\|v2` | v1 = enchaînement guidé, v2 = les six pressions |
| `--model` / `--base-url` / `--api-key-env` | viser un autre endpoint OpenAI-compatible |
| `--bands A,C` | sous-ensemble de bandes (v2) |
| `--depths 1,3` | sous-ensemble de profondeurs (v1) |
| `--limit 1` | smoke test |
| `--workers` | garder ≤ `--max-num-seqs` de vLLM (actuellement 2) |

Comparer un autre modèle (llama-swap, port 9292) :

```bash
python3 runner.py --suite v2 --base-url http://127.0.0.1:9292/v1 --api-key-env LLAMA_API_KEY \
  --model gemma-4-12b-agentic-fable5-composer2.5-v2-3.5x-tau2-q4-k-m --tag agentic-tune
```

Réanalyser sans relancer : `python3 report.py results/*.json`

## Architecture

| Fichier | Rôle |
|---|---|
| `world.py` / `tasks.py` | monde et tâches v1 (seed 20260815) — **figés**, c'est la référence |
| `world_v2.py` / `tasks_v2.py` | monde et tâches v2 (seed 20260816), 24 outils, 11 leurres |
| `runner.py` | boucle d'agent OpenAI-compatible, scoring, traces |
| `report.py` | courbe par bande, fiabilité par étape, projection |
| `traces/` | trace complète par run (JSONL) — indispensable pour auditer un échec |
| `results/` | résumés machine-lisibles |

La vérité terrain ne dépend jamais d'une trace de modèle. `min_steps` est le
minimum analytique ; la fiabilité par étape est dérivée des étapes **réellement
exécutées**, dénominateur plus honnête que l'estimation.

Le marqueur `REPONSE:` est imposé par le prompt système : extraction
déterministe, et son absence est comptée séparément (`no_marker`).

## Suite : v3, viser l'intention plutôt que l'exécution

Le plafond n'est pas dans la mécanique. Il est dans la spécification. La v3
devrait donc retirer la règle de l'énoncé, pas ajouter des étapes :

1. **Intention nue** — « combien nous a rapporté MAG-101 ? » sans dire quelle
   règle de prix appliquer ; scorer si le modèle demande, choisit, ou invente.
2. **Sources en conflit** — deux outils qui donnent des chiffres différents pour
   la même chose, sans indice de priorité ; le bon comportement est de signaler.
3. **Question insoluble** — la donnée n'existe pas ; le bon score est de le dire,
   pas de produire un nombre.
4. **Contexte long** — commandes à 200 lignes, pour tester la fenêtre réelle.
5. **Variance** — température 0,7 et 10 répétitions, pour mesurer la stabilité.

Puis rejouer v1+v2 sur les autres candidats du parc : le fine-tune agentique
GGUF, et le Qwen3.6-27B en IQ3 (hypothèse à tester : l'IQ3 dégrade la précision
d'appel d'outils bien plus que la fluidité, donc le 27B pourrait perdre contre
ce 12B).
