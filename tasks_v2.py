"""
Suite v2: four bands, each isolating a pressure that v1 did not apply.

  A_selection  - entity named not identified, 24 tools, 6 candidates to sift
  B_branching  - answer depends on a fetched value; a stale aggregate tool
                 (get_stock_global) flips the branch if trusted
  C_recovery   - a tool that fails on purpose, fallback required per line
  D_composite  - all of the above at ~18 calls

Ground truth is computed here, from the world, never from a model trace.
"""

from collections import Counter

from world_v2 import ENTREPOTS, W

_P = W["produits"]
_F = W["fournisseurs"]
_C = W["commandes"]

SEUIL_STOCK = 100


def _unique_famille(style: str) -> tuple[str, str]:
    """Return (famille appearing exactly once in the style group, its ref)."""
    group = W["style_groups"][style]
    counts = Counter(_P[r]["famille"] for r in group)
    for ref in group:
        if counts[_P[ref]["famille"]] == 1:
            return _P[ref]["famille"], ref
    raise RuntimeError(f"pas de famille unique pour {style}")


def _stock_reel(ref: str) -> int:
    return sum(W["stock_entrepot"][ref].values())


def _prix_applicable(client_id: str, ref: str) -> float:
    return W["tarifs"].get((client_id, ref), _P[ref]["prix_unitaire"])


def build_tasks() -> list[dict]:
    tasks: list[dict] = []

    # --- A: selection pressure + under-specification -------------------------
    for i, style in enumerate(["Lumia", "Vela", "Kalix", "Solis", "Onyx"], 1):
        famille, ref = _unique_famille(style)
        fournisseur = _F[_P[ref]["fournisseur_id"]]
        tasks.append({
            "id": f"A-{i:02d}",
            "band": "A_selection",
            # Analytic minimum: search + one lucky candidate + supplier. The
            # statement guarantees uniqueness, so stopping at the first match is
            # valid; a systematic scan costs up to 8.
            "min_steps": 3,
            "question": (
                f"Parmi les produits dont le nom contient \"{style}\", un seul appartient a la "
                f"famille \"{famille}\". Quel est le pays du fournisseur de ce produit ?"
            ),
            "expected": fournisseur["pays"],
            "kind": "str",
        })

    # --- B: branching, with a stale aggregate that flips it ------------------
    # Pick refs where get_stock_global sits on the wrong side of the threshold.
    pieges = [r for r in sorted(_P)
              if (_stock_reel(r) < SEUIL_STOCK) != (W["stock_global"][r] < SEUIL_STOCK)]
    bas = [r for r in pieges if _stock_reel(r) < SEUIL_STOCK]
    haut = [r for r in pieges if _stock_reel(r) >= SEUIL_STOCK]
    # Balance both branches, otherwise the conditional is never really exercised.
    selection = [bas[0], haut[0], bas[1], haut[1], bas[2]]
    for i, ref in enumerate(selection, 1):
        reel = _stock_reel(ref)
        if reel < SEUIL_STOCK:
            expected = _F[_P[ref]["fournisseur_id"]]["delai_jours"]
            kind, min_steps = "int", 1 + len(ENTREPOTS) + 2
        else:
            expected = _P[ref]["prix_unitaire"]
            kind, min_steps = "float", 1 + len(ENTREPOTS) + 1
        tasks.append({
            "id": f"B-{i:02d}",
            "band": "B_branching",
            "min_steps": min_steps,
            "question": (
                f"Calcule le stock reel de la reference {ref} en cumulant les stocks de tous les "
                f"entrepots. Si ce cumul est strictement inferieur a {SEUIL_STOCK}, reponds le "
                f"delai de livraison en jours du fournisseur de ce produit. Sinon, reponds son "
                f"prix unitaire catalogue."
            ),
            "expected": expected,
            "kind": kind,
        })

    # --- C: error recovery, per line ----------------------------------------
    for i, (cid, oid) in enumerate(W["pool_recovery"][:5], 1):
        lignes = _C[oid]["lignes"]
        total = round(sum(_prix_applicable(cid, l["ref"]) * l["quantite"] for l in lignes), 2)
        sans_tarif = sum(1 for l in lignes if (cid, l["ref"]) not in W["tarifs"])
        tasks.append({
            "id": f"C-{i:02d}",
            "band": "C_recovery",
            "min_steps": 1 + len(lignes) + sans_tarif + 1,
            "question": (
                f"Pour la commande {oid} du client {cid}, calcule le montant total. Pour chaque "
                f"ligne, applique le tarif negocie du client sur cette reference s'il en existe un, "
                f"et sinon le prix unitaire catalogue. Multiplie par la quantite de la ligne."
            ),
            "expected": total,
            "kind": "float",
        })

    # --- D: composite -------------------------------------------------------
    for i, mid in enumerate(W["pool_composite"][:5], 1):
        oids = sorted(o["id"] for o in _C.values() if o["magasin_id"] == mid)
        total, n_lignes, sans_tarif = 0.0, 0, 0
        for oid in oids:
            cid = _C[oid]["client_id"]
            for l in _C[oid]["lignes"]:
                total += _prix_applicable(cid, l["ref"]) * l["quantite"]
                n_lignes += 1
                if (cid, l["ref"]) not in W["tarifs"]:
                    sans_tarif += 1
        tasks.append({
            "id": f"D-{i:02d}",
            "band": "D_composite",
            "min_steps": 1 + len(oids) + n_lignes + sans_tarif + 1,
            "question": (
                f"Calcule le chiffre d'affaires total du magasin {mid} sur l'ensemble de ses "
                f"commandes. Pour chaque ligne de chaque commande, applique le tarif negocie du "
                f"client de la commande sur cette reference s'il en existe un, sinon le prix "
                f"unitaire catalogue, multiplie par la quantite."
            ),
            "expected": round(total, 2),
            "kind": "float",
        })

    return tasks


TASKS = build_tasks()


if __name__ == "__main__":
    for t in TASKS:
        print(f"{t['id']:6s} {t['band']:13s} min={t['min_steps']:2d} "
              f"attendu={t['expected']!r:>12}  {t['question'][:70]}...")
    print(f"\n{len(TASKS)} taches, min_steps de {min(t['min_steps'] for t in TASKS)} "
          f"a {max(t['min_steps'] for t in TASKS)}")
