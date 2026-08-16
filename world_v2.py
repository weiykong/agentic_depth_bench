"""
World v2: same shape as v1, but built to break agents rather than to flatter them.

Six pressures absent from v1:
  1. selection    - 24 tools, including near-duplicates and plausible decoys
  2. recovery     - get_tarif_negocie fails for most pairs, forcing a fallback
  3. under-spec   - entities named, not identified; the path is not stated
  4. branching    - the answer depends on a value fetched mid-chain
  5. distractors  - get_stock_global is a STALE aggregate that disagrees with
                    the sum over warehouses, on purpose and across the threshold
  6. depth        - composite tasks need ~20 calls

v1 is frozen as the baseline, so this world has its own seed and its own data.
"""

import json
import random

from world import t_calculer  # safe arithmetic evaluator, reused as-is

SEED_V2 = 20260816

FAMILLES = ["Facade", "Caisson", "Plan de travail", "Poignee", "Electromenager"]
PAYS = ["France", "Allemagne", "Italie", "Pologne", "Espagne"]
REGIONS = ["Est", "Ouest", "Nord", "Sud", "Ile-de-France"]
STYLES = ["Lumia", "Arcos", "Vela", "Nordis", "Ombra", "Kalix", "Terra", "Solis",
          "Mistral", "Zephyr", "Basalt", "Cedre", "Onyx", "Perle", "Ambre"]
ENTREPOTS = ["ENT-NORD", "ENT-SUD", "ENT-EST", "ENT-OUEST"]


def _build() -> dict:
    rng = random.Random(SEED_V2)

    fournisseurs, contrats = {}, {}
    for i in range(1, 21):
        fid = f"FRN-{i:03d}"
        fournisseurs[fid] = {
            "id": fid,
            "nom": f"Fournisseur {i}",
            "pays": rng.choice(PAYS),
            "delai_jours": rng.randint(3, 45),
        }
        # Only ~half have a contract: the other half force a fallback branch.
        if i % 2 == 1:
            contrats[fid] = {"fournisseur_id": fid, "reference_contrat": f"CTR-{i:03d}",
                             "remise_pct": rng.choice([2, 5, 8, 12])}

    # --- products, grouped by style so search returns several candidates -----
    produits = {}
    style_groups: dict[str, list[str]] = {}
    ref_no = 1
    for style in STYLES:
        # Exactly one product of this style carries `target`; the others do not.
        target = rng.choice(FAMILLES)
        others = [f for f in FAMILLES if f != target]
        familles = [rng.choice(others) for _ in range(6)]
        familles[rng.randrange(6)] = target
        group = []
        for slot in range(6):
            ref = f"REF-{ref_no:03d}"
            ref_no += 1
            produits[ref] = {
                "ref": ref,
                "nom": f"{style} {slot + 1}",
                "famille": familles[slot],
                "prix_unitaire": round(rng.uniform(15.0, 950.0), 2),
                "fournisseur_id": f"FRN-{rng.randint(1, 20):03d}",
            }
            group.append(ref)
        style_groups[style] = group

    refs = list(produits)

    # --- warehouse stock, plus a deliberately stale global aggregate ---------
    stock_entrepot, stock_global = {}, {}
    for ref in refs:
        per = {e: rng.randint(0, 60) for e in ENTREPOTS}
        stock_entrepot[ref] = per
        total = sum(per.values())
        # For half the catalogue the stale aggregate sits on the OTHER side of
        # the 100 threshold, so trusting it flips the branch.
        if rng.random() < 0.5:
            stock_global[ref] = total + (80 if total < 100 else -80)
        else:
            stock_global[ref] = total + rng.randint(-5, 5)

    historique_prix = {
        ref: [{"annee": a, "prix": round(produits[ref]["prix_unitaire"] * rng.uniform(0.75, 0.95), 2)}
              for a in (2023, 2024, 2025)]
        for ref in refs
    }

    magasins = {f"MAG-{i:03d}": {"id": f"MAG-{i:03d}", "nom": f"Magasin {i}",
                                 "region": rng.choice(REGIONS)} for i in range(1, 13)}

    clients, commandes, tarifs = {}, {}, {}
    order_seq = 1

    def _commande(cid: str, mid: str, lignes: list[dict]) -> str:
        nonlocal order_seq
        oid = f"CMD-{order_seq:04d}"
        order_seq += 1
        commandes[oid] = {"id": oid, "client_id": cid, "magasin_id": mid,
                          "statut": rng.choice(["en_preparation", "expediee", "livree"]),
                          "lignes": lignes}
        return oid

    # Generic clients.
    for idx in range(1, 21):
        cid = f"CLI-{idx:03d}"
        mid = f"MAG-{rng.randint(1, 12):03d}"
        clients[cid] = {"id": cid, "nom": f"Client {idx}", "magasin_id": mid}
        for _ in range(rng.randint(1, 2)):
            _commande(cid, mid, [{"ref": rng.choice(refs), "quantite": rng.randint(1, 6)}
                                 for _ in range(rng.randint(1, 3))])

    # Recovery pool: one order of 5 lines, exactly 2 refs with a negotiated price.
    pool_recovery = []
    for idx in range(21, 31):
        cid = f"CLI-{idx:03d}"
        mid = f"MAG-{rng.randint(1, 12):03d}"
        clients[cid] = {"id": cid, "nom": f"Client {idx}", "magasin_id": mid}
        lignes_refs = rng.sample(refs, 5)
        oid = _commande(cid, mid, [{"ref": r, "quantite": rng.randint(1, 5)} for r in lignes_refs])
        for r in lignes_refs[:2]:
            tarifs[(cid, r)] = round(produits[r]["prix_unitaire"] * rng.uniform(0.60, 0.85), 2)
        pool_recovery.append((cid, oid))

    # Composite pool: a dedicated store, 3 clients, 3 orders, 8 lines, some tariffs.
    pool_composite = []
    for k in range(5):
        mid = f"MAG-{101 + k:03d}"
        magasins[mid] = {"id": mid, "nom": f"Magasin {101 + k}", "region": rng.choice(REGIONS)}
        shapes = [3, 3, 2]
        for j, n_lines in enumerate(shapes):
            cid = f"CLI-{200 + k * 3 + j:03d}"
            clients[cid] = {"id": cid, "nom": f"Client {200 + k * 3 + j}", "magasin_id": mid}
            chosen = rng.sample(refs, n_lines)
            _commande(cid, mid, [{"ref": r, "quantite": rng.randint(1, 4)} for r in chosen])
            for r in chosen[:1]:  # one negotiated line per order
                tarifs[(cid, r)] = round(produits[r]["prix_unitaire"] * rng.uniform(0.60, 0.85), 2)
        pool_composite.append(mid)

    return {
        "fournisseurs": fournisseurs, "contrats": contrats, "produits": produits,
        "style_groups": style_groups, "stock_entrepot": stock_entrepot,
        "stock_global": stock_global, "historique_prix": historique_prix,
        "magasins": magasins, "clients": clients, "commandes": commandes,
        "tarifs": tarifs, "pool_recovery": pool_recovery, "pool_composite": pool_composite,
    }


W = _build()


# --- core tools -------------------------------------------------------------

def t_get_produit(ref: str):
    return W["produits"].get(str(ref).strip().upper()) or {"erreur": f"reference inconnue: {ref}"}


def t_get_produit_detail(ref: str):
    """Near-duplicate of get_produit with extra, mostly useless fields."""
    p = W["produits"].get(str(ref).strip().upper())
    if not p:
        return {"erreur": f"reference inconnue: {ref}"}
    return {**p, "code_douanier": "9403 40", "poids_kg": round(len(p["nom"]) * 1.7, 1),
            "emballage": "carton", "norme": "EN 1116"}


def t_chercher_produit(nom: str):
    """Substring search. Returns ref and nom only - not famille."""
    q = str(nom).strip().casefold()
    hits = [{"ref": p["ref"], "nom": p["nom"]} for p in W["produits"].values()
            if q in p["nom"].casefold()]
    return {"resultats": sorted(hits, key=lambda h: h["ref"]), "nombre": len(hits)}


def t_get_fournisseur(fournisseur_id: str):
    return W["fournisseurs"].get(str(fournisseur_id).strip().upper()) or \
        {"erreur": f"fournisseur inconnu: {fournisseur_id}"}


def t_get_fournisseur_par_nom(nom: str):
    q = str(nom).strip().casefold()
    for f in W["fournisseurs"].values():
        if f["nom"].casefold() == q:
            return f
    return {"erreur": f"aucun fournisseur nomme {nom}"}


def t_get_contrat_fournisseur(fournisseur_id: str):
    fid = str(fournisseur_id).strip().upper()
    return W["contrats"].get(fid) or {"erreur": f"aucun contrat pour {fid}"}


def t_get_commande(commande_id: str):
    return W["commandes"].get(str(commande_id).strip().upper()) or \
        {"erreur": f"commande inconnue: {commande_id}"}


def t_get_client(client_id: str):
    return W["clients"].get(str(client_id).strip().upper()) or \
        {"erreur": f"client inconnu: {client_id}"}


def t_get_magasin(magasin_id: str):
    return W["magasins"].get(str(magasin_id).strip().upper()) or \
        {"erreur": f"magasin inconnu: {magasin_id}"}


def t_list_commandes_client(client_id: str):
    cid = str(client_id).strip().upper()
    if cid not in W["clients"]:
        return {"erreur": f"client inconnu: {cid}"}
    return {"client_id": cid,
            "commandes": sorted(o["id"] for o in W["commandes"].values() if o["client_id"] == cid)}


def t_list_commandes_magasin(magasin_id: str):
    mid = str(magasin_id).strip().upper()
    if mid not in W["magasins"]:
        return {"erreur": f"magasin inconnu: {mid}"}
    return {"magasin_id": mid,
            "commandes": sorted(o["id"] for o in W["commandes"].values() if o["magasin_id"] == mid)}


def t_list_entrepots():
    return {"entrepots": list(ENTREPOTS)}


def t_get_stock_entrepot(ref: str, entrepot: str):
    r, e = str(ref).strip().upper(), str(entrepot).strip().upper()
    if r not in W["stock_entrepot"]:
        return {"erreur": f"reference inconnue: {r}"}
    if e not in ENTREPOTS:
        return {"erreur": f"entrepot inconnu: {e}. Utiliser list_entrepots."}
    return {"ref": r, "entrepot": e, "stock": W["stock_entrepot"][r][e]}


def t_get_stock_global(ref: str):
    """Aggregate from the nightly export. Known to drift from warehouse reality."""
    r = str(ref).strip().upper()
    if r not in W["stock_global"]:
        return {"erreur": f"reference inconnue: {r}"}
    return {"ref": r, "stock_global": W["stock_global"][r], "source": "export_nocturne"}


def t_get_tarif_negocie(client_id: str, ref: str):
    key = (str(client_id).strip().upper(), str(ref).strip().upper())
    if key in W["tarifs"]:
        return {"client_id": key[0], "ref": key[1], "tarif_negocie": W["tarifs"][key]}
    return {"erreur": f"aucun tarif negocie pour {key[0]} sur {key[1]}"}


def t_get_historique_prix(ref: str):
    r = str(ref).strip().upper()
    if r not in W["historique_prix"]:
        return {"erreur": f"reference inconnue: {r}"}
    return {"ref": r, "historique": W["historique_prix"][r]}


# --- decoys: plausible, well-documented, and useless for these tasks --------

def t_get_livraison(commande_id: str):
    oid = str(commande_id).strip().upper()
    if oid not in W["commandes"]:
        return {"erreur": f"commande inconnue: {oid}"}
    return {"commande_id": oid, "transporteur": "Geodis", "suivi": f"TRK{oid[-4:]}9021"}


def t_get_facture(commande_id: str):
    oid = str(commande_id).strip().upper()
    if oid not in W["commandes"]:
        return {"erreur": f"commande inconnue: {oid}"}
    return {"commande_id": oid, "facture": f"FAC-{oid[-4:]}", "statut_paiement": "regle"}


def t_list_produits_famille(famille: str):
    q = str(famille).strip().casefold()
    return {"refs": sorted(p["ref"] for p in W["produits"].values() if p["famille"].casefold() == q)}


def t_get_promotion(ref: str):
    r = str(ref).strip().upper()
    if r not in W["produits"]:
        return {"erreur": f"reference inconnue: {r}"}
    return {"ref": r, "promotion_active": False, "campagne": None}


def t_get_avis_client(client_id: str):
    cid = str(client_id).strip().upper()
    if cid not in W["clients"]:
        return {"erreur": f"client inconnu: {cid}"}
    return {"client_id": cid, "note_moyenne": 4.1, "nombre_avis": 3}


def t_convertir_devise(montant: float, devise: str):
    taux = {"USD": 1.09, "GBP": 0.85, "CHF": 0.96}
    d = str(devise).strip().upper()
    if d not in taux:
        return {"erreur": f"devise non supportee: {d}"}
    return {"montant_converti": round(float(montant) * taux[d], 2), "devise": d}


def t_get_taux_tva(pays: str):
    taux = {"FRANCE": 20.0, "ALLEMAGNE": 19.0, "ITALIE": 22.0, "POLOGNE": 23.0, "ESPAGNE": 21.0}
    p = str(pays).strip().upper()
    return {"pays": p, "taux_tva": taux.get(p)} if p in taux else {"erreur": f"pays inconnu: {pays}"}


TOOL_IMPL = {
    "get_produit": t_get_produit,
    "get_produit_detail": t_get_produit_detail,
    "chercher_produit": t_chercher_produit,
    "get_fournisseur": t_get_fournisseur,
    "get_fournisseur_par_nom": t_get_fournisseur_par_nom,
    "get_contrat_fournisseur": t_get_contrat_fournisseur,
    "get_commande": t_get_commande,
    "get_client": t_get_client,
    "get_magasin": t_get_magasin,
    "list_commandes_client": t_list_commandes_client,
    "list_commandes_magasin": t_list_commandes_magasin,
    "list_entrepots": t_list_entrepots,
    "get_stock_entrepot": t_get_stock_entrepot,
    "get_stock_global": t_get_stock_global,
    "get_tarif_negocie": t_get_tarif_negocie,
    "get_historique_prix": t_get_historique_prix,
    "calculer": t_calculer,
    "get_livraison": t_get_livraison,
    "get_facture": t_get_facture,
    "list_produits_famille": t_list_produits_famille,
    "get_promotion": t_get_promotion,
    "get_avis_client": t_get_avis_client,
    "convertir_devise": t_convertir_devise,
    "get_taux_tva": t_get_taux_tva,
}

# Tools that no task in this suite legitimately needs. Calls to these are
# counted as selection errors, not as failures.
DECOY_TOOLS = {"get_livraison", "get_facture", "get_promotion", "get_avis_client",
               "convertir_devise", "get_taux_tva", "get_fournisseur_par_nom",
               "list_produits_famille", "get_historique_prix", "get_stock_global",
               "get_produit_detail"}


def _fn(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}


_S = {"type": "string"}
_N = {"type": "number"}

TOOL_SCHEMAS = [
    _fn("get_produit", "Fiche produit : nom, famille, prix unitaire catalogue, fournisseur.",
        {"ref": {**_S, "description": "Reference, ex: REF-012"}}, ["ref"]),
    _fn("get_produit_detail", "Fiche produit etendue (logistique, normes, emballage).",
        {"ref": _S}, ["ref"]),
    _fn("chercher_produit", "Recherche des produits dont le nom contient le texte donne.",
        {"nom": {**_S, "description": "Texte recherche, ex: Lumia"}}, ["nom"]),
    _fn("get_fournisseur", "Fiche fournisseur : pays et delai de livraison en jours.",
        {"fournisseur_id": _S}, ["fournisseur_id"]),
    _fn("get_fournisseur_par_nom", "Fiche fournisseur recherchee par son nom exact.",
        {"nom": _S}, ["nom"]),
    _fn("get_contrat_fournisseur", "Contrat cadre d'un fournisseur, s'il en existe un.",
        {"fournisseur_id": _S}, ["fournisseur_id"]),
    _fn("get_commande", "Commande avec son client, son magasin et ses lignes (ref, quantite).",
        {"commande_id": _S}, ["commande_id"]),
    _fn("get_client", "Fiche client.", {"client_id": _S}, ["client_id"]),
    _fn("get_magasin", "Fiche magasin.", {"magasin_id": _S}, ["magasin_id"]),
    _fn("list_commandes_client", "Identifiants des commandes d'un client.",
        {"client_id": _S}, ["client_id"]),
    _fn("list_commandes_magasin", "Identifiants des commandes d'un magasin.",
        {"magasin_id": _S}, ["magasin_id"]),
    _fn("list_entrepots", "Liste des entrepots existants.", {}, []),
    _fn("get_stock_entrepot", "Stock reel d'une reference dans UN entrepot donne.",
        {"ref": _S, "entrepot": {**_S, "description": "Code entrepot, voir list_entrepots"}},
        ["ref", "entrepot"]),
    _fn("get_stock_global", "Stock agrege issu de l'export nocturne (peut etre decale du reel).",
        {"ref": _S}, ["ref"]),
    _fn("get_tarif_negocie", "Tarif negocie d'un client sur une reference. Echoue s'il n'en existe pas.",
        {"client_id": _S, "ref": _S}, ["client_id", "ref"]),
    _fn("get_historique_prix", "Historique des prix d'une reference par annee (2023-2025).",
        {"ref": _S}, ["ref"]),
    _fn("calculer", "Evalue une expression arithmetique (+ - * / et parentheses).",
        {"expression": _S}, ["expression"]),
    _fn("get_livraison", "Informations de transport d'une commande.", {"commande_id": _S}, ["commande_id"]),
    _fn("get_facture", "Facture et statut de paiement d'une commande.", {"commande_id": _S}, ["commande_id"]),
    _fn("list_produits_famille", "Toutes les references d'une famille produit.", {"famille": _S}, ["famille"]),
    _fn("get_promotion", "Promotion en cours sur une reference.", {"ref": _S}, ["ref"]),
    _fn("get_avis_client", "Note moyenne et nombre d'avis d'un client.", {"client_id": _S}, ["client_id"]),
    _fn("convertir_devise", "Convertit un montant en euros vers une autre devise.",
        {"montant": _N, "devise": _S}, ["montant", "devise"]),
    _fn("get_taux_tva", "Taux de TVA applicable dans un pays.", {"pays": _S}, ["pays"]),
]


def call_tool(name: str, arguments: str) -> tuple[str, str | None]:
    if name not in TOOL_IMPL:
        return json.dumps({"erreur": f"outil inconnu: {name}"}, ensure_ascii=False), "unknown_tool"
    try:
        args = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        return json.dumps({"erreur": "arguments JSON invalides"}, ensure_ascii=False), "bad_json_args"
    if not isinstance(args, dict):
        return json.dumps({"erreur": "arguments doivent etre un objet"}, ensure_ascii=False), "bad_json_args"
    try:
        result = TOOL_IMPL[name](**args)
    except TypeError as exc:
        return json.dumps({"erreur": f"parametres invalides: {exc}"}, ensure_ascii=False), "bad_params"

    kind = None
    if name in DECOY_TOOLS:
        kind = "decoy_call"
    if isinstance(result, dict) and "erreur" in result:
        # A failed get_tarif_negocie is the expected recovery signal, not an error.
        kind = "expected_miss" if name == "get_tarif_negocie" else (kind or "tool_lookup_miss")
    return json.dumps(result, ensure_ascii=False), kind


if __name__ == "__main__":
    print(f"produits={len(W['produits'])} fournisseurs={len(W['fournisseurs'])} "
          f"clients={len(W['clients'])} commandes={len(W['commandes'])} "
          f"outils={len(TOOL_SCHEMAS)} leurres={len(DECOY_TOOLS)}")
    print("pool_recovery:", W["pool_recovery"][:2])
    print("pool_composite:", W["pool_composite"])
