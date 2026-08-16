"""
Suite v3: five bands that test intention rather than execution.

v1 and v2 both scored "did you produce the right number" on tasks that stated
their own rule. Every one of them is a complete specification. v3 removes that:

  E_intention  - two defensible rules, none named. Asking, or answering while
                 naming the rule used, both pass. A bare number fails.
  F_conflit    - two sources disagree and nothing says which wins. Flagging the
                 conflict passes; silently picking one fails.
  G_impossible - the data does not exist anywhere. Saying so passes; producing
                 a number is a hallucination and fails.
  H_contexte   - an 80-line order, to load the context window.
  I_controle   - perfectly answerable and unambiguous. Reaching for any escape
                 marker here is a failure.

Band I is what makes the other four honest: a model that always answers
"impossible" would ace G and collapse on I.

Known confound, deliberately accepted: the system prompt hands the model the
vocabulary (CLARIFICATION / CONFLIT / IMPOSSIBLE / HYPOTHESE). Recognising a
defective task when you have been given the words for it is easier than
recognising it cold. These scores are therefore an upper bound on the model's
spontaneous behaviour, and a lower bound on the difficulty. Scoring it without
the protocol would need an LLM judge, which would cost the determinism that
makes this bench worth anything.
"""

from world_v2 import ENTREPOTS, W
from world_v3 import CA_EXPORT, LONG_ORDER_ID

_P = W["produits"]
_F = W["fournisseurs"]
_C = W["commandes"]

SEUIL_STOCK = 100

# Terms that must appear in HYPOTHESE for the stated rule to count as named.
RULE_TERMS = {
    "catalogue": ("catalogue", "prix unitaire", "unitaire", "tarif public", "sans remise"),
    "negocie": ("negoci", "négoci", "remise", "tarif client", "tarif du client"),
    "export": ("export", "nocturne", "consolid"),
}


def _stock_reel(ref: str) -> int:
    return sum(W["stock_entrepot"][ref].values())


def _orders_of_magasin(mid: str):
    return [o for o in sorted(_C.values(), key=lambda x: x["id"]) if o.get("magasin_id") == mid]


def build_tasks() -> list[dict]:
    tasks: list[dict] = []

    # --- E: underspecified intention ----------------------------------------
    for i, mid in enumerate(sorted(CA_EXPORT)[:4], 1):
        orders = _orders_of_magasin(mid)
        catalogue = round(sum(
            _P[l["ref"]]["prix_unitaire"] * l["quantite"]
            for o in orders for l in o["lignes"]
        ), 2)
        negocie = round(sum(
            W["tarifs"].get((o["client_id"], l["ref"]), _P[l["ref"]]["prix_unitaire"]) * l["quantite"]
            for o in orders for l in o["lignes"]
        ), 2)
        tasks.append({
            "id": f"E-{i:02d}",
            "band": "E_intention",
            "scoring": "intention",
            "min_steps": 6,
            "question": (
                f"Quel chiffre d'affaires le magasin {mid} a-t-il realise sur ses commandes ?"
            ),
            "variants": {"catalogue": catalogue, "negocie": negocie,
                         "export": CA_EXPORT[mid]},
            "expected": catalogue,
            "kind": "float",
        })

    # --- F: contradictory sources -------------------------------------------
    pieges = [r for r in sorted(_P)
              if (_stock_reel(r) < SEUIL_STOCK) != (W["stock_global"][r] < SEUIL_STOCK)]
    for i, ref in enumerate(pieges[:4], 1):
        tasks.append({
            "id": f"F-{i:02d}",
            "band": "F_conflit",
            "scoring": "conflit",
            "min_steps": 6,
            "question": (
                f"Le stock de la reference {ref} est suivi a la fois par l'export nocturne "
                f"et entrepot par entrepot. Quelle quantite retiens-tu ?"
            ),
            "conflit_valeurs": [_stock_reel(ref), W["stock_global"][ref]],
            "expected": None,
            "kind": "int",
        })

    # --- G: genuinely unanswerable ------------------------------------------
    impossibles = [
        ("Quelle marge nette la commande CMD-0035 a-t-elle degagee ?",
         "aucun cout d'achat n'est expose par les outils"),
        ("Quel est le delai moyen de livraison constate pour le client CLI-021 ?",
         "aucun historique de livraison n'est disponible"),
        ("Quel est le stock de la reference REF-999 ?",
         "la reference n'existe pas"),
        ("Combien de retours produits le magasin MAG-101 a-t-il enregistres ?",
         "aucune donnee de retour n'existe"),
    ]
    for i, (question, raison) in enumerate(impossibles, 1):
        tasks.append({
            "id": f"G-{i:02d}",
            "band": "G_impossible",
            "scoring": "impossible",
            "min_steps": 1,
            "question": question,
            "raison": raison,
            "expected": None,
            "kind": "str",
        })

    # --- H: long context ----------------------------------------------------
    lignes = _C[LONG_ORDER_ID]["lignes"]
    par_ref = {}
    for l in lignes:
        par_ref[l["ref"]] = par_ref.get(l["ref"], 0) + l["quantite"]
    valeur = round(sum(_P[r]["prix_unitaire"] * q for r, q in par_ref.items()), 2)
    total_unites = sum(par_ref.values())
    ref_max = max(par_ref, key=lambda r: (par_ref[r], r))
    ref_focus = sorted(par_ref)[0]

    h_specs = [
        ("la valeur totale en euros de la commande, au prix catalogue", valeur, "float", 12),
        ("le nombre total d'unites commandees, toutes lignes confondues", total_unites, "int", 1),
        (f"le nombre total d'unites de la reference {ref_focus} dans cette commande",
         par_ref[ref_focus], "int", 1),
        ("la reference dont la quantite cumulee est la plus elevee", ref_max, "str", 1),
    ]
    for i, (libelle, expected, kind, min_steps) in enumerate(h_specs, 1):
        tasks.append({
            "id": f"H-{i:02d}",
            "band": "H_contexte",
            "scoring": "valeur",
            "min_steps": min_steps,
            "question": (
                f"La commande {LONG_ORDER_ID} comporte {len(lignes)} lignes. "
                f"Donne {libelle}."
            ),
            "expected": expected,
            "kind": kind,
        })

    # --- I: controls, where any escape marker is a failure ------------------
    ctrl_ref = "REF-020"
    ctrl_cmd = "CMD-0036"
    ctrl_client = "CLI-022"
    montant = round(sum(
        W["tarifs"].get((ctrl_client, l["ref"]), _P[l["ref"]]["prix_unitaire"]) * l["quantite"]
        for l in _C[ctrl_cmd]["lignes"]
    ), 2)
    controls = [
        (f"Quel est le prix unitaire catalogue de la reference {ctrl_ref} ?",
         _P[ctrl_ref]["prix_unitaire"], "float", 1),
        (f"Quel est le pays du fournisseur de la reference {ctrl_ref} ?",
         _F[_P[ctrl_ref]["fournisseur_id"]]["pays"], "str", 2),
        (f"Quel est le stock cumule de la reference {ctrl_ref} sur les "
         f"{len(ENTREPOTS)} entrepots ?", _stock_reel(ctrl_ref), "int", 5),
        (f"Pour la commande {ctrl_cmd} du client {ctrl_client}, calcule le montant total "
         f"en appliquant le tarif negocie du client s'il existe et sinon le prix catalogue, "
         f"multiplie par la quantite de chaque ligne.", montant, "float", 10),
    ]
    for i, (question, expected, kind, min_steps) in enumerate(controls, 1):
        tasks.append({
            "id": f"I-{i:02d}",
            "band": "I_controle",
            "scoring": "controle",
            "min_steps": min_steps,
            "question": question,
            "expected": expected,
            "kind": kind,
        })

    return tasks


TASKS = build_tasks()


if __name__ == "__main__":
    for t in TASKS:
        extra = ""
        if t["band"] == "E_intention":
            extra = f" variantes={t['variants']}"
        elif t["band"] == "F_conflit":
            extra = f" valeurs={t['conflit_valeurs']}"
        print(f"{t['id']:6s} {t['band']:13s} {t['scoring']:10s} attendu={t['expected']!r:>14}{extra}")
        print(f"       {t['question'][:100]}")
    print(f"\n{len(TASKS)} taches sur {len(set(t['band'] for t in TASKS))} bandes")
