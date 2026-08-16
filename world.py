"""
Deterministic toy world + tool implementations.

The world is generated from a fixed seed so every run is reproducible and the
ground truth of each task can be computed directly in Python, independently of
the path the model takes through the tools.

Tools are pure functions with no side effects. They are intentionally simple:
we are measuring the model's ability to chain calls, not its ability to cope
with a badly designed API.
"""

import ast
import json
import operator
import random

SEED = 20260815

FAMILLES = ["Facade", "Caisson", "Plan de travail", "Poignee", "Electromenager"]
PAYS = ["France", "Allemagne", "Italie", "Pologne", "Espagne"]
REGIONS = ["Est", "Ouest", "Nord", "Sud", "Ile-de-France"]


def _build_world() -> dict:
    rng = random.Random(SEED)

    fournisseurs = {}
    for i in range(1, 16):
        fid = f"FRN-{i:03d}"
        fournisseurs[fid] = {
            "id": fid,
            "nom": f"Fournisseur {i}",
            "pays": rng.choice(PAYS),
            "delai_jours": rng.randint(3, 45),
        }

    produits = {}
    for i in range(1, 61):
        ref = f"REF-{i:03d}"
        produits[ref] = {
            "ref": ref,
            "nom": f"Produit {i}",
            "famille": rng.choice(FAMILLES),
            "prix_unitaire": round(rng.uniform(12.0, 890.0), 2),
            "stock": rng.randint(0, 400),
            "fournisseur_id": f"FRN-{rng.randint(1, 15):03d}",
        }

    magasins = {}
    for i in range(1, 13):
        mid = f"MAG-{i:03d}"
        magasins[mid] = {
            "id": mid,
            "nom": f"Magasin {i}",
            "region": rng.choice(REGIONS),
        }

    clients = {}
    commandes = {}
    refs = list(produits)
    order_seq = 1

    # Clients are constructed with an explicit order/line shape so that tasks of
    # a given depth are guaranteed to exist. CLI-001..020 are generic; the pools
    # below are reserved for the deeper task families.
    def _new_client(idx: int) -> str:
        cid = f"CLI-{idx:03d}"
        clients[cid] = {
            "id": cid,
            "nom": f"Client {idx}",
            "magasin_id": f"MAG-{rng.randint(1, 12):03d}",
        }
        return cid

    def _new_commande(cid: str, lignes: list[dict]) -> str:
        nonlocal order_seq
        oid = f"CMD-{order_seq:04d}"
        order_seq += 1
        commandes[oid] = {
            "id": oid,
            "client_id": cid,
            "statut": rng.choice(["en_preparation", "expediee", "livree"]),
            "lignes": lignes,
        }
        return oid

    # Generic clients: 1 to 2 orders, 1 to 3 lines each.
    for idx in range(1, 21):
        cid = _new_client(idx)
        for _ in range(rng.randint(1, 2)):
            lignes = [
                {"ref": rng.choice(refs), "quantite": rng.randint(1, 6)}
                for _ in range(rng.randint(1, 3))
            ]
            _new_commande(cid, lignes)

    # Depth-6 pool: exactly 2 orders, exactly 1 line each.
    pool_d6 = []
    for idx in range(21, 31):
        cid = _new_client(idx)
        for _ in range(2):
            _new_commande(cid, [{"ref": rng.choice(refs), "quantite": rng.randint(1, 6)}])
        pool_d6.append(cid)

    # Depth-10 pool: exactly 3 orders holding 5 distinct refs in total.
    pool_d10 = []
    for idx in range(31, 41):
        cid = _new_client(idx)
        chosen = rng.sample(refs, 5)
        shapes = [chosen[0:2], chosen[2:4], chosen[4:5]]
        for shape in shapes:
            _new_commande(cid, [{"ref": r, "quantite": rng.randint(1, 6)} for r in shape])
        pool_d10.append(cid)

    return {
        "fournisseurs": fournisseurs,
        "produits": produits,
        "magasins": magasins,
        "clients": clients,
        "commandes": commandes,
        "pool_d6": pool_d6,
        "pool_d10": pool_d10,
    }


WORLD = _build_world()


# --- Safe arithmetic evaluator ---------------------------------------------

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("expression non autorisee")


# --- Tool implementations ---------------------------------------------------


def t_get_produit(ref: str):
    p = WORLD["produits"].get(str(ref).strip().upper())
    return p if p else {"erreur": f"reference inconnue: {ref}"}


def t_get_fournisseur(fournisseur_id: str):
    f = WORLD["fournisseurs"].get(str(fournisseur_id).strip().upper())
    return f if f else {"erreur": f"fournisseur inconnu: {fournisseur_id}"}


def t_get_commande(commande_id: str):
    c = WORLD["commandes"].get(str(commande_id).strip().upper())
    return c if c else {"erreur": f"commande inconnue: {commande_id}"}


def t_get_client(client_id: str):
    c = WORLD["clients"].get(str(client_id).strip().upper())
    return c if c else {"erreur": f"client inconnu: {client_id}"}


def t_get_magasin(magasin_id: str):
    m = WORLD["magasins"].get(str(magasin_id).strip().upper())
    return m if m else {"erreur": f"magasin inconnu: {magasin_id}"}


def t_list_commandes_client(client_id: str):
    cid = str(client_id).strip().upper()
    if cid not in WORLD["clients"]:
        return {"erreur": f"client inconnu: {client_id}"}
    ids = sorted(o["id"] for o in WORLD["commandes"].values() if o["client_id"] == cid)
    return {"client_id": cid, "commandes": ids}


def t_calculer(expression: str):
    try:
        tree = ast.parse(str(expression), mode="eval")
        return {"resultat": round(float(_safe_eval(tree)), 4)}
    except Exception as exc:  # noqa: BLE001 - surfaced to the model as a tool error
        return {"erreur": f"expression invalide: {exc}"}


TOOL_IMPL = {
    "get_produit": t_get_produit,
    "get_fournisseur": t_get_fournisseur,
    "get_commande": t_get_commande,
    "get_client": t_get_client,
    "get_magasin": t_get_magasin,
    "list_commandes_client": t_list_commandes_client,
    "calculer": t_calculer,
}


def _fn(name, desc, props, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
            },
        },
    }


TOOL_SCHEMAS = [
    _fn("get_produit", "Retourne la fiche d'un produit a partir de sa reference.",
        {"ref": {"type": "string", "description": "Reference produit, ex: REF-012"}}, ["ref"]),
    _fn("get_fournisseur", "Retourne la fiche d'un fournisseur (pays, delai en jours).",
        {"fournisseur_id": {"type": "string", "description": "Identifiant fournisseur, ex: FRN-003"}},
        ["fournisseur_id"]),
    _fn("get_commande", "Retourne une commande avec ses lignes (ref et quantite).",
        {"commande_id": {"type": "string", "description": "Identifiant commande, ex: CMD-0012"}},
        ["commande_id"]),
    _fn("get_client", "Retourne la fiche d'un client.",
        {"client_id": {"type": "string", "description": "Identifiant client, ex: CLI-004"}}, ["client_id"]),
    _fn("get_magasin", "Retourne la fiche d'un magasin (nom, region).",
        {"magasin_id": {"type": "string", "description": "Identifiant magasin, ex: MAG-002"}}, ["magasin_id"]),
    _fn("list_commandes_client", "Liste les identifiants de commandes d'un client.",
        {"client_id": {"type": "string", "description": "Identifiant client, ex: CLI-004"}}, ["client_id"]),
    _fn("calculer", "Evalue une expression arithmetique (+ - * / et parentheses).",
        {"expression": {"type": "string", "description": "Ex: 12.5*3 + 40"}}, ["expression"]),
]


def call_tool(name: str, arguments: str) -> tuple[str, str | None]:
    """Execute a tool call. Returns (json_result, error_kind|None)."""
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
    err = "tool_lookup_miss" if isinstance(result, dict) and "erreur" in result else None
    return json.dumps(result, ensure_ascii=False), err


if __name__ == "__main__":
    w = WORLD
    print(f"produits={len(w['produits'])} fournisseurs={len(w['fournisseurs'])} "
          f"clients={len(w['clients'])} commandes={len(w['commandes'])} "
          f"magasins={len(w['magasins'])}")
    print("pool_d6:", w["pool_d6"][:3], "pool_d10:", w["pool_d10"][:3])
