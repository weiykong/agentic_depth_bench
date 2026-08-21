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

## Suite v3 — l'intention plutôt que l'exécution (2026-08-16)

v1 et v2 énoncent toutes deux la règle à appliquer : le modèle exécute une
spécification complète. La v3 la retire. Température **0,7**, 5 répétitions.

| Bande | n | Succès | Étapes moy. / min | Latence |
|---|---|---|---|---|
| E_intention — deux règles défendables, aucune nommée | 20 | **0 %** | 1,0 / 6 | 1,0 s |
| F_conflit — deux sources qui se contredisent | 20 | 100 % | 6,0 / 6 | 4,0 s |
| G_impossible — la donnée n'existe nulle part | 20 | 75 % | 5,7 / 1 | 4,2 s |
| H_contexte — commande de 80 lignes | 20 | 40 % | 6,3 / 3,8 | 27,9 s |
| I_controle — question saine, aucun marqueur attendu | 20 | 100 % | 5,2 / 4,5 | 3,5 s |

**La bande I est ce qui rend les autres crédibles.** Un modèle qui répondrait
« impossible » à tout obtiendrait 100 % sur G et s'effondrerait sur I. Zéro
marqueur indu sur 20 contrôles : les scores de F et G ne sont pas gonflés par
un réflexe d'esquive.

### E_intention : échec total, 0 sur 20

Sur les quatre magasins et les cinq répétitions, le modèle a **toujours** rendu
un nombre nu, en un seul appel d'outil, sans jamais demander de précision ni
nommer sa source. Il prend systématiquement `get_ca_magasin_export`, qui est une
réponse défendable — trois sources le sont ici — mais il ne dit jamais laquelle
il a retenue.

Ce n'est pas une erreur de calcul, c'est une absence de signalement. Dans un
pipeline sans supervision, cela produit un chiffre faux avec l'assurance d'un
chiffre juste.

### H_contexte : la dérive arithmétique

80 lignes de résultat d'outil cassent l'agrégation. Le plus net est H-02
(compter les unités, réponse attendue 209) : **0/5, et cinq réponses
différentes** — 197, 194, 205, 207, 202. Toujours proche, jamais exact. La
latence passe à 27,9 s contre 3 à 5 s ailleurs.

### G_impossible : hallucination par substitution

15/20. Les échecs sont concentrés sur G-01 (marge nette) : le modèle calcule
quelque chose à partir des données disponibles et l'appelle marge — il a produit
-906,65 et 807,65. Il ne dit pas « je ne sais pas », il fabrique une grandeur
voisine. Les trois autres cas insolubles sont correctement signalés.

### Variance à 0,7

12 tâches sur 20 varient entre répétitions. La nature de la variance diffère
selon la bande : sur F et G elle porte sur la **stratégie** (demander une
précision ou signaler le conflit — les deux passent), sur H elle porte sur la
**valeur**, et c'est ce qui la fait échouer.

### Confond assumé

Le prompt système fournit le vocabulaire (`CLARIFICATION`, `CONFLIT`,
`IMPOSSIBLE`, `HYPOTHESE`), et ce même prompt est appliqué à toutes les tâches,
contrôles compris, pour que sa présence ne signale pas quelles questions sont
défectueuses. Reconnaître une tâche défectueuse quand on vous en donne les mots
reste plus facile que la reconnaître à froid : ces scores sont donc une borne
haute du comportement spontané. Scorer sans ce protocole exigerait un juge LLM,
au prix du déterminisme qui fait tout l'intérêt de ce banc.

### Pourquoi aucune projection par étape sur la v3

La formule p = succès^(1/étapes) suppose une chaîne qui casse une étape à la
fois. Les échecs de la v3 sont comportementaux — réponse nue, valeur inventée,
dérive arithmétique. Extrapoler à partir d'eux produirait un chiffre confiant et
dénué de sens. `report.py` la supprime donc explicitement sur cette suite.

## Ce que ces trois runs établissent

La mécanique agentique est **acquise** à 12B sur des tâches bien spécifiées :
enchaînement à 19 étapes, sélection parmi 24 outils, branchement conditionnel,
récupération d'erreur, résistance à un distracteur construit pour tromper.

Borne de confiance : avec 15/15 sur la bande D, la borne basse à 95 %
(Clopper-Pearson) sur le succès bout-en-bout est 81,9 %, soit une fiabilité
**par étape ≥ 98,9 %** sur 19 étapes réellement exécutées.

L'hypothèse de départ — ~90 % par étape, donc effondrement à 35 % sur 10 étapes —
est réfutée. Elle ne l'est pas « un peu » : elle est fausse d'un ordre de grandeur
sur le taux d'échec.

## La conclusion des trois suites

**La mécanique est acquise, l'intention ne l'est pas.**

Tant que la règle est écrite dans l'énoncé, le modèle exécute sans faute :
19 étapes, 24 outils, branchement, récupération d'erreur, distracteur construit
pour tromper — 120/120. Dès que la règle disparaît de l'énoncé, il tombe à 0 %,
non par erreur de calcul mais parce qu'il ne signale rien.

Le goulot n'est donc pas la capacité agentique du modèle. C'est la spécification
de la tâche. Ce qui a une conséquence directe sur le choix des cas d'usage :
un pipeline dont la règle métier est écrite quelque part est faisable en local ;
un agent censé deviner ce que veut l'utilisateur ne l'est pas.

## Comparaison locale vs API OpenAI (2026-08-19)

Mêmes trois suites, sur `gpt-5.6-terra` (API OpenAI, `reasoning_effort=none`
pour rester comparable à la convention déjà utilisée par `vba_benchmark`).
Coût réel mesuré sur les traces (`usage` des réponses) : **$3,01** pour les
180 runs — v1 $0,19, v2 $1,26, v3 $1,55.

| Bande | gemma-4-12b (local) | gpt-5.6-terra (API) |
|---|---|---|
| v1 (toutes profondeurs) | 100 % | 100 % |
| v2 (toutes bandes) | 100 % | 100 % |
| G_impossible | 75 % | 90 % |
| H_contexte | 40 % | 80 % |
| I_controle | 100 % | 100 % |
| F_conflit | 100 % | 100 % |
| **E_intention** | **0 %** | **5 %** |

Deux enseignements :

- **La mécanique agentique ne distingue pas les modèles ici** : v1 et v2 sont
  à 100 % des deux côtés, chaînage à 19+ étapes compris. Payer pour l'API
  n'achète rien sur ce terrain — le 12B local avait déjà atteint le plafond
  mesurable.
- **Le modèle frontière encaisse mieux la dérive de contexte long**
  (H_contexte 80 % contre 40 %) et l'insoluble (G_impossible 90 % contre
  75 %) — c'est là que la puissance brute paie.
- **E_intention ne bouge presque pas : 5 % contre 0 %.** Un modèle bien plus
  cher et plus récent tombe quasiment dans le même trou. Ce n'est donc pas un
  artefact de taille de modèle ni un problème que l'argent résout : le défaut
  de signalement d'hypothèse implicite semble être une propriété de classe,
  pas une limite du 12B. Ça renforce la conclusion du run initial — la
  spécification de la tâche est le goulot, pas la capacité du modèle, quel
  que soit son prix.

v1 mesuré ici avec `--reps 1` (n=5/profondeur) contre `--reps 3` (n=15) pour
gemma — comparaison qualitative valable (100 % des deux côtés reste 100 %
avec moins de reps), mais un intervalle de confiance comparable demanderait
de relancer avec `--reps 3`.

Bug de plateforme rencontré : `gpt-5.6-terra` est un modèle de raisonnement,
il rejette `temperature`/`max_tokens` (HTTP 400). `runner.py` détecte
désormais `api.openai.com` dans `--base-url` et bascule automatiquement sur
`max_completion_tokens` + `reasoning_effort` (même convention que
`vba_benchmark/models.py`), et journalise `usage` pour permettre le chiffrage
a posteriori.

## Comparaison qwen3.8-27b-iq3 (llama-swap, MTP) — 2026-08-21

Même trois suites, sur `qwen3.8-27b-iq3` (bartowski/Qwen3.8-27B-GGUF, quant
IQ3_M, ~12,9 Go, couches MTP natives — `--spec-type draft-mtp
--spec-draft-n-max 2` actif et vérifié via `draft_n`/`draft_n_accepted` dans
les timings). Local, gratuit, via llama-swap (port 9292).

| Bande | gemma-4-12b | gpt-5.6-terra | **qwen3.8-27b-iq3** |
|---|---|---|---|
| v1 (toutes profondeurs) | 100 % | 100 % | **100 %** |
| v2 (toutes bandes) | 100 % | 100 % | **100 %** |
| I_controle | 100 % | 100 % | **100 %** |
| G_impossible | 75 % | 90 % | **75 %** |
| **F_conflit** | 100 % | 100 % | **0 %** |
| **H_contexte** | 40 % | 80 % | **0 %** (58,3 % après correctif, voir plus bas) |
| E_intention | 0 % | 5 % | **0 %** |

n=12 (reps=3) pour qwen3.8-27b-iq3 contre n=20 (reps=5) pour les deux autres —
même réserve que pour la comparaison gpt-5.6-terra : comparaison qualitative
valable, intervalle de confiance non comparable terme à terme.

### F_conflit : le même défaut d'intention, mais qui déborde

Sur les deux autres modèles, F_conflit est acquis à 100 %. Ici, 0/12. La trace
de F-01 montre que le travail mécanique est correct — 6/6 étapes, le bon
calcul (36+39+39+14 = 128 contre un agrégat système à 48) — mais le modèle
**résout le conflit en silence** au lieu de le signaler :

> « L'export nocturne étant un agrégat qui peut être décalé du réel, je
> retiens la somme des stocks réels par entrepôt. REPONSE: 128 »

Même défaut que E_intention (chiffre juste, source non nommée, aucun
marqueur de conflit), mais qui ici déborde sur une bande où gemma-4-12b et
gpt-5.6-terra ne trébuchent jamais. Ce n'est pas un artefact de budget : la
réponse est complète et cohérente, juste non signalée.

### H_contexte : budget de sortie, puis un vrai plafond

0/12 en premier passage — mais la trace ne ressemblait pas à un échec de
raisonnement : un seul appel d'outil (`get_commande`, ~80 lignes de JSON),
puis `content` vide, aucun tool_call, ~1100 tokens de complétion consommés
malgré `--max-tokens 1024`. Le modèle n'échouait pas la tâche, il ne
l'atteignait jamais — budget épuisé en réflexion interne (`reasoning_content`)
avant d'avoir écrit quoi que ce soit en sortie.

Retest ciblé, `--bands H_contexte --max-tokens 4096` (n=12) :

| Tâche | 1024 tokens | 4096 tokens |
|---|---|---|
| H-01 | 0/3, silence | **3/3**, correct (114852,91) |
| H-04 | 0/3, silence | **3/3**, correct (REF-017) |
| H-03 | 0/3, silence | 1/3 correct (21), 2/3 valeur fausse (25) |
| H-02 | 0/3, silence | **0/3, silence** — même à 4096 |

58,3 % (7/12) au global. Deux tâches sur quatre (H-01, H-04) n'étaient
**que** du budget : une fois la marge donnée, réponse correcte à 100 %. Les
deux autres révèlent une vraie limite : H-03 se trompe de valeur une fois sur
la marge donnée (25 au lieu de 21), et H-02 — qui demande de sommer 80
quantités dans une liste répétitive — calcule un total faux (215 au lieu de
209 via son propre appel à `calculer`) puis **s'arrête sans jamais écrire la
réponse**, même avec 6038 tokens de complétion consommés (au-dessus du
plafond de 4096 — la réflexion n'y est visiblement pas non plus strictement
comptée côté serveur). Plus de budget retarde l'échec, il ne le corrige pas :
l'extraction/sommation numérique sur une liste longue et répétitive reste un
vrai point faible de cette quantification.

### Verdict

**La mécanique est acquise, l'intention ne l'est pas — et à cette
quantification, elle est même moins fiable que chez les deux autres modèles
sur ce point précis.** v1 et v2 sont parfaits (120/120 à eux deux, MTP actif,
donc pas de compromis vitesse/qualité visible sur ce terrain). Mais
F_conflit qui s'effondre à 0 % alors qu'il est acquis ailleurs, et H_contexte
qui ne remonte qu'à 58 % même en corrigeant le vrai bug de budget, disent la
même chose : **ce modèle-là, dans cette quantification, n'est pas fait pour
tourner sans supervision sur des tâches qui demandent de repérer un conflit
ou de faire un calcul fiable sur une longue liste.** Il est utilisable pour
de l'enchaînement d'outils bien spécifié (v1/v2, où il égale les deux autres
modèles gratuitement et localement), pas pour un pipeline qui doit détecter
tout seul qu'une réponse est douteuse.

Leçon de plateforme, généralisable aux prochaines comparaisons : le
`--max-tokens 1024` par défaut de `runner.py` est calibré pour des modèles
non-raisonneurs. Un modèle qui écrit dans `reasoning_content` avant `content`
peut se taire complètement à ce budget sans que ce soit un échec de
capacité — `--max-tokens 4096` (voire plus) est le minimum à essayer avant de
conclure quoi que ce soit sur un modèle de cette famille.

## Ce qui reste hors périmètre

- le **jugement** — aucune tâche n'a de réponse discutable ;
- les **actions irréversibles** — tous les outils sont en lecture ;
- le **multi-tour** — l'utilisateur ne répond jamais aux demandes de précision ;
- la **reconnaissance à froid** — voir le confond assumé de la v3 ;
- le **contexte réellement long** — 80 lignes chargent la fenêtre, pas 131 k.

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
python3 runner.py --suite v3 --reps 5 --temperature 0.7 --max-tokens 2048 --tag full
```

Aucune dépendance : bibliothèque standard uniquement (Python 3.14 sur sc-lab).

| Option | Effet |
|---|---|
| `--suite v1\|v2\|v3` | v1 = enchaînement guidé, v2 = les six pressions, v3 = l'intention |
| `--temperature` | 0 par défaut ; 0,7 pour mesurer la variance (v3) |
| `--model` / `--base-url` / `--api-key-env` | viser un autre endpoint OpenAI-compatible |
| `--bands A,C` | sous-ensemble de bandes (v2, v3) |
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
| `world_v3.py` / `tasks_v3.py` | monde et tâches v3 (seed 20260817), intention, conflit, insoluble, contexte long |
| `runner.py` | boucle d'agent OpenAI-compatible, scoring, traces |
| `report.py` | courbe par bande, fiabilité par étape, projection |
| `traces/` | trace complète par run (JSONL) — indispensable pour auditer un échec |
| `results/` | résumés machine-lisibles |

La vérité terrain ne dépend jamais d'une trace de modèle. `min_steps` est le
minimum analytique ; la fiabilité par étape est dérivée des étapes **réellement
exécutées**, dénominateur plus honnête que l'estimation.

Le marqueur `REPONSE:` est imposé par le prompt système : extraction
déterministe, et son absence est comptée séparément (`no_marker`).

## Suite : ce qui reste à faire

Le banc a trouvé où ça casse. Deux directions, par ordre de valeur :

1. **Comparer les modèles.** Fait pour l'API OpenAI (`gpt-5.6-terra`) et pour
   Qwen3.8-27B en IQ3 (`qwen3.8-27b-iq3`, voir ci-dessus — verdict : mécanique
   au niveau des deux autres, mais F_conflit et H_contexte en net retrait,
   pas déployable sans supervision). Reste à rejouer v1+v2+v3 sur le
   fine-tune agentique GGUF et sur le Qwen3.6-27B en IQ3 (hypothèse
   toujours ouverte : l'IQ3 dégrade la précision d'appel d'outils bien plus
   que la fluidité — à confirmer ou infirmer sur un second modèle 27B avant
   de généraliser à la taille plutôt qu'à ce checkpoint précis). Une commande
   par modèle via `--base-url`, `--max-tokens 4096` si le modèle raisonne.
2. **Attaquer E autrement.** Le modèle échoue à 0 % en rendant un nombre nu.
   Vérifier si un prompt système qui exige explicitement de nommer la source à
   chaque réponse chiffrée suffit à corriger ça, ou si le défaut résiste. C'est
   la question qui décide si le problème se règle par ingénierie de prompt ou
   par choix de modèle — et donc si un pipeline local est déployable sans
   supervision humaine.
