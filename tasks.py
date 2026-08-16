"""
Task suite, graded by the minimum number of tool calls needed to answer.

Every task carries a ground truth computed directly from the world, never from
a model trace. `min_steps` is the analytic minimum number of tool calls; the
model may take more, which is recorded as a separate diagnostic.
"""

from world import WORLD

_P = WORLD["produits"]
_F = WORLD["fournisseurs"]
_C = WORLD["commandes"]


def _orders_of(client_id: str) -> list[dict]:
    return [o for o in sorted(_C.values(), key=lambda x: x["id"]) if o["client_id"] == client_id]


def build_tasks() -> list[dict]:
    tasks: list[dict] = []

    # --- depth 1: one lookup -------------------------------------------------
    d1_specs = [
        ("REF-007", "stock", "Quel est le stock", "int"),
        ("REF-019", "prix_unitaire", "Quel est le prix unitaire en euros", "float"),
        ("REF-032", "famille", "Quelle est la famille", "str"),
        ("REF-044", "stock", "Quel est le stock", "int"),
        ("REF-058", "prix_unitaire", "Quel est le prix unitaire en euros", "float"),
    ]
    for i, (ref, field, label, kind) in enumerate(d1_specs, 1):
        tasks.append({
            "id": f"d1-{i:02d}",
            "depth": 1,
            "min_steps": 1,
            "question": f"{label} de la reference {ref} ?",
            "expected": _P[ref][field],
            "kind": kind,
        })

    # --- depth 3: order -> product -> supplier -------------------------------
    d3_orders = ["CMD-0003", "CMD-0011", "CMD-0020", "CMD-0027", "CMD-0034"]
    d3_fields = ["delai_jours", "pays", "delai_jours", "pays", "delai_jours"]
    for i, (oid, field) in enumerate(zip(d3_orders, d3_fields), 1):
        ref = _C[oid]["lignes"][0]["ref"]
        fournisseur = _F[_P[ref]["fournisseur_id"]]
        label = "delai de livraison en jours" if field == "delai_jours" else "pays"
        tasks.append({
            "id": f"d3-{i:02d}",
            "depth": 3,
            "min_steps": 3,
            "question": (
                f"Pour la commande {oid}, considere le produit de sa premiere ligne. "
                f"Quel est le {label} du fournisseur de ce produit ?"
            ),
            "expected": fournisseur[field],
            "kind": "int" if field == "delai_jours" else "str",
        })

    # --- depth 6: 2 orders, 1 line each, sum of unit prices ------------------
    for i, cid in enumerate(WORLD["pool_d6"][:5], 1):
        orders = _orders_of(cid)
        refs = [o["lignes"][0]["ref"] for o in orders]
        total = round(sum(_P[r]["prix_unitaire"] for r in refs), 2)
        tasks.append({
            "id": f"d6-{i:02d}",
            "depth": 6,
            "min_steps": 6,
            "question": (
                f"Le client {cid} a passe plusieurs commandes, chacune avec une seule ligne. "
                f"Quelle est la somme des prix unitaires des produits concernes ?"
            ),
            "expected": total,
            "kind": "float",
        })

    # --- depth 10: 3 orders, 5 distinct refs, total order value --------------
    for i, cid in enumerate(WORLD["pool_d10"][:5], 1):
        orders = _orders_of(cid)
        total = round(
            sum(_P[l["ref"]]["prix_unitaire"] * l["quantite"] for o in orders for l in o["lignes"]),
            2,
        )
        tasks.append({
            "id": f"d10-{i:02d}",
            "depth": 10,
            "min_steps": 10,
            "question": (
                f"Quelle est la valeur totale de toutes les commandes du client {cid}, "
                f"c'est-a-dire la somme sur chaque ligne du prix unitaire multiplie par la quantite ?"
            ),
            "expected": total,
            "kind": "float",
        })

    return tasks


TASKS = build_tasks()


if __name__ == "__main__":
    for t in TASKS:
        print(f"{t['id']:8s} depth={t['depth']:2d}  attendu={t['expected']!r:>22}  {t['question'][:78]}")
