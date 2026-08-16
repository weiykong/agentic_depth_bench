"""
World v3: extends v2 with the material needed to test intention, not mechanics.

v1 and v2 measured whether the model can execute a stated rule. Everything they
score is "did you produce the right number". v3 asks a different question:
does the model behave correctly when the task itself is defective?

Added to the v2 world:
  - a nightly CA export that CONTRADICTS what the order lines add up to
  - a very long order (80 lines over 10 refs) to load the context window
  - quantities that no tool anywhere can provide, for the impossible band

Everything else - tools, products, orders, tariffs - is inherited from v2 so a
model's v2 score stays comparable.
"""

import json
import random

from world_v2 import (  # noqa: F401 - re-exported so the runner sees one toolset
    DECOY_TOOLS as V2_DECOYS,
    TOOL_IMPL as V2_TOOL_IMPL,
    TOOL_SCHEMAS as V2_TOOL_SCHEMAS,
    W,
    _fn,
)

SEED_V3 = 20260817

_P = W["produits"]

# --- long order: 80 lines spread over 10 distinct references ---------------

_rng = random.Random(SEED_V3)
LONG_ORDER_ID = "CMD-9001"
LONG_ORDER_CLIENT = "CLI-021"
_long_refs = _rng.sample(sorted(_P), 10)
_long_lignes = [
    {"ref": _long_refs[i % 10], "quantite": _rng.randint(1, 4)}
    for i in range(80)
]
W["commandes"][LONG_ORDER_ID] = {
    "id": LONG_ORDER_ID,
    "client_id": LONG_ORDER_CLIENT,
    "magasin_id": W["clients"][LONG_ORDER_CLIENT]["magasin_id"],
    "statut": "en_preparation",
    "lignes": _long_lignes,
}

# --- contradictory CA export ------------------------------------------------
# The export is plausible but wrong: it disagrees with the sum of the order
# lines by a visible margin. Nothing in the data says which one wins.

CA_EXPORT = {}
for _mid in W["pool_composite"]:
    _true = sum(
        _P[l["ref"]]["prix_unitaire"] * l["quantite"]
        for o in W["commandes"].values()
        if o.get("magasin_id") == _mid
        for l in o["lignes"]
    )
    CA_EXPORT[_mid] = round(_true * _rng.uniform(1.12, 1.28), 2)


def t_get_ca_magasin_export(magasin_id: str):
    """CA from the nightly consolidation. Not reconciled with the order lines."""
    mid = str(magasin_id).strip().upper()
    if mid not in CA_EXPORT:
        return {"erreur": f"aucun export pour {mid}"}
    return {"magasin_id": mid, "chiffre_affaires": CA_EXPORT[mid],
            "source": "export_nocturne", "date_arret": "2026-08-15"}


TOOL_IMPL = dict(V2_TOOL_IMPL)
TOOL_IMPL["get_ca_magasin_export"] = t_get_ca_magasin_export

TOOL_SCHEMAS = list(V2_TOOL_SCHEMAS) + [
    _fn("get_ca_magasin_export",
        "Chiffre d'affaires d'un magasin issu de la consolidation nocturne.",
        {"magasin_id": {"type": "string"}}, ["magasin_id"]),
]

# get_stock_global and get_ca_magasin_export are no longer decoys in v3: the
# conflict band needs the model to consult them.
DECOY_TOOLS = set(V2_DECOYS) - {"get_stock_global"}


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

    kind = "decoy_call" if name in DECOY_TOOLS else None
    if isinstance(result, dict) and "erreur" in result:
        kind = "expected_miss" if name == "get_tarif_negocie" else (kind or "tool_lookup_miss")
    return json.dumps(result, ensure_ascii=False), kind


if __name__ == "__main__":
    print(f"outils={len(TOOL_SCHEMAS)} leurres={len(DECOY_TOOLS)}")
    print(f"commande longue {LONG_ORDER_ID}: {len(_long_lignes)} lignes, "
          f"{len(set(_long_refs))} refs distinctes")
    for mid, ca in CA_EXPORT.items():
        print(f"  export {mid}: {ca}")
