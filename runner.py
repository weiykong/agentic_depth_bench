"""
Agent loop against any OpenAI-compatible endpoint, with deterministic scoring.

Usage:
    VLLM_API_KEY=... python3 runner.py --model gemma-4-12b-it-w4a16 \
        --base-url http://127.0.0.1:8000/v1 --reps 3

Writes one JSONL trace per run under traces/ and a summary JSON under results/.
Only the standard library is used, so no virtualenv is required.
"""

import argparse
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def load_suite(name: str):
    """Return (tasks, tool_schemas, call_tool, decoys, system_prompt)."""
    if name == "v1":
        import tasks as t
        import world as w
        return t.TASKS, w.TOOL_SCHEMAS, w.call_tool, set(), SYSTEM_PROMPT
    if name == "v2":
        import tasks_v2 as t
        import world_v2 as w
        return t.TASKS, w.TOOL_SCHEMAS, w.call_tool, w.DECOY_TOOLS, SYSTEM_PROMPT
    if name == "v3":
        import tasks_v3 as t
        import world_v3 as w
        return t.TASKS, w.TOOL_SCHEMAS, w.call_tool, w.DECOY_TOOLS, SYSTEM_PROMPT_V3
    raise SystemExit(f"suite inconnue: {name}")



SYSTEM_PROMPT = (
    "Tu es un assistant qui repond a des questions sur une base de donnees interne.\n"
    "Tu n'as aucune connaissance prealable de ces donnees : tu dois obligatoirement "
    "utiliser les outils fournis pour obtenir chaque information.\n"
    "N'invente jamais une valeur. Enchaine autant d'appels d'outils que necessaire.\n"
    "Quand tu as la reponse finale, termine ton message par une ligne exactement au format :\n"
    "REPONSE: <valeur>\n"
    "La valeur est un nombre brut (sans unite, sans symbole, point decimal) ou un mot."
)

# v3 hands the model a vocabulary for defective tasks. Every v3 task gets this
# same prompt, including the controls, so the presence of the vocabulary cannot
# by itself signal that a given task is defective.
SYSTEM_PROMPT_V3 = SYSTEM_PROMPT + (
    "\n\n"
    "Toutes les questions ne sont pas saines. Selon le cas, termine par :\n"
    "- Question ambigue (plusieurs regles de calcul defendables) : soit une seule ligne\n"
    "  CLARIFICATION: <ta question>\n"
    "  soit les deux lignes\n"
    "  HYPOTHESE: <la regle que tu as choisie>\n"
    "  REPONSE: <valeur>\n"
    "- Deux sources de donnees qui se contredisent : une seule ligne\n"
    "  CONFLIT: <les deux valeurs et leur source>\n"
    "- Donnee necessaire absente du systeme : une seule ligne\n"
    "  IMPOSSIBLE: <raison>\n"
    "Si la question est claire et que la donnee existe, reponds normalement avec "
    "REPONSE: et n'utilise aucun de ces trois marqueurs."
)


# --- scoring ----------------------------------------------------------------


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


# Serving stacks leak chat-template control tokens into message content
# (observed with vLLM's gemma4 tool parser: "<|channel>thought<channel|>").
# They are an artifact of the stack, not a model answer, so we strip them
# before looking for the marker.
_CTRL_TOKEN_RE = re.compile(r"<\|?[a-zA-Z_][a-zA-Z_0-9]*\|?>")
_MARKER_RE = re.compile(r"REPONSE\s*:\s*(.+)")


def extract_answer(text: str) -> str | None:
    """Return the value of the last REPONSE: marker, if present."""
    if not text:
        return None
    cleaned = _CTRL_TOKEN_RE.sub(" ", _strip_accents(text)).upper()
    matches = _MARKER_RE.findall(cleaned)
    if not matches:
        return None
    return matches[-1].strip().strip("*`_ ").strip()


_V3_MARKERS = ("CLARIFICATION", "CONFLIT", "IMPOSSIBLE", "HYPOTHESE", "REPONSE")


def extract_markers(text: str) -> dict:
    """Return every v3 marker present, keyed by name, last occurrence winning."""
    if not text:
        return {}
    cleaned = _CTRL_TOKEN_RE.sub(" ", _strip_accents(text)).upper()
    found = {}
    for name in _V3_MARKERS:
        matches = re.findall(rf"{name}\s*:\s*(.+)", cleaned)
        if matches:
            found[name] = matches[-1].strip().strip("*`_ ").strip()
    return found


def _cites_value(text: str, value) -> bool:
    """True when a number appears in the text, tolerating separators."""
    digits = "".join(c for c in str(value) if c.isdigit())
    flat = "".join(c for c in text if c.isdigit())
    return bool(digits) and digits in flat


def is_correct(answer: str | None, expected, kind: str) -> bool:
    if answer is None:
        return False
    if kind in ("int", "float"):
        cleaned = (
            answer.lower().replace(" ", "").replace(" ", "").replace(" ", "")
            .replace("euros", "").replace("EUR", "").replace("eur", "")
            .replace("jours", "").replace("€", "").replace(",", ".").strip()
        )
        # keep a leading sign, digits and a single decimal point
        keep = "".join(c for c in cleaned if c.isdigit() or c in ".-")
        try:
            return abs(float(keep) - float(expected)) <= 0.05
        except ValueError:
            return False
    return _strip_accents(answer).strip().casefold() == _strip_accents(str(expected)).strip().casefold()


def score_run(task: dict, final_text: str) -> tuple[bool, str, str | None]:
    """Return (correct, verdict, answer_shown) for any suite.

    v1/v2 score a value. v3 scores behaviour: asking, flagging a conflict or
    declaring a task impossible can each be the correct outcome, and on the
    control band reaching for any of those markers is a failure.
    """
    scoring = task.get("scoring", "valeur")
    markers = extract_markers(final_text)
    reponse = markers.get("REPONSE")
    escapes = [m for m in ("CLARIFICATION", "CONFLIT", "IMPOSSIBLE") if m in markers]

    if scoring in ("valeur", "controle"):
        if scoring == "controle" and escapes:
            return False, f"marqueur_indu:{escapes[0].lower()}", reponse
        if reponse is None:
            return False, "aucune_reponse", None
        ok = is_correct(reponse, task["expected"], task["kind"])
        return ok, "ok" if ok else "valeur_fausse", reponse

    if scoring == "impossible":
        if "IMPOSSIBLE" in markers:
            return True, "impossible_signale", markers["IMPOSSIBLE"][:120]
        if "CLARIFICATION" in markers:
            return True, "clarification_demandee", markers["CLARIFICATION"][:120]
        if reponse is not None:
            return False, "valeur_inventee", reponse
        return False, "aucun_marqueur", None

    if scoring == "intention":
        if "CLARIFICATION" in markers:
            return True, "clarification_demandee", markers["CLARIFICATION"][:120]
        hypothese = markers.get("HYPOTHESE")
        if hypothese and reponse is not None:
            from tasks_v3 import RULE_TERMS
            hyp = _strip_accents(hypothese).casefold()
            for rule, value in task["variants"].items():
                if not is_correct(reponse, value, "float"):
                    continue
                terms = tuple(_strip_accents(t).casefold() for t in RULE_TERMS[rule])
                if any(t in hyp for t in terms):
                    return True, f"hypothese_{rule}", reponse
                return False, "hypothese_non_reliee", reponse
            return False, "valeur_hors_regles", reponse
        if reponse is not None:
            return False, "reponse_nue", reponse
        return False, "aucun_marqueur", None

    if scoring == "conflit":
        valeurs = task["conflit_valeurs"]
        if "CONFLIT" in markers:
            both = all(_cites_value(markers["CONFLIT"], v) for v in valeurs)
            return True, "conflit_chiffre" if both else "conflit_signale", markers["CONFLIT"][:120]
        if markers.get("HYPOTHESE") and reponse is not None:
            if any(is_correct(reponse, v, "int") for v in valeurs):
                return True, "source_explicitee", reponse
            return False, "valeur_hors_sources", reponse
        if "CLARIFICATION" in markers:
            return True, "clarification_demandee", markers["CLARIFICATION"][:120]
        if reponse is not None:
            return False, "choix_silencieux", reponse
        return False, "aucun_marqueur", None

    return False, f"scoring_inconnu:{scoring}", reponse


# --- transport --------------------------------------------------------------


def chat(base_url: str, api_key: str, model: str, messages: list, tools: list,
         timeout: int, max_tokens: int, temperature: float) -> dict:
    body = json.dumps({
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


# --- one run ----------------------------------------------------------------


def run_task(task: dict, rep: int, cfg) -> dict:
    messages = [
        {"role": "system", "content": cfg.system_prompt},
        {"role": "user", "content": task["question"]},
    ]
    max_steps = max(task["min_steps"] * 2 + 6, 16)
    trace, errors = [], []
    steps = decoy_calls = 0
    started = time.time()
    final_text, stop_reason = "", "ok"

    for _ in range(max_steps + 1):
        try:
            data = chat(cfg.base_url, cfg.api_key, cfg.model, messages,
                        cfg.tool_schemas, cfg.timeout, cfg.max_tokens,
                        cfg.temperature)
        except urllib.error.HTTPError as exc:
            stop_reason = f"http_{exc.code}"
            errors.append(stop_reason)
            trace.append({"type": "http_error", "code": exc.code,
                          "body": exc.read()[:400].decode(errors="replace")})
            break
        except Exception as exc:  # noqa: BLE001 - network/timeout surfaced as a failed run
            stop_reason = "transport_error"
            errors.append(f"transport:{type(exc).__name__}")
            trace.append({"type": "transport_error", "detail": str(exc)[:400]})
            break

        msg = data["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        trace.append({
            "type": "assistant",
            "content": (msg.get("content") or "")[:1500],
            "tool_calls": [{"name": c["function"]["name"],
                            "arguments": c["function"]["arguments"]} for c in calls],
        })

        if not calls:
            final_text = msg.get("content") or ""
            break

        messages.append({
            "role": "assistant",
            "content": msg.get("content") or "",
            "tool_calls": calls,
        })
        for c in calls:
            steps += 1
            name = c["function"]["name"]
            if name in cfg.decoys:
                decoy_calls += 1
            result, err = cfg.call_tool(name, c["function"]["arguments"])
            if err:
                errors.append(err)
            trace.append({"type": "tool", "name": name,
                          "arguments": c["function"]["arguments"],
                          "result": result[:800], "error": err})
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})

        if steps > max_steps:
            stop_reason = "step_limit"
            break
    else:
        stop_reason = "step_limit"

    correct, verdict, answer = score_run(task, final_text)
    if stop_reason == "ok" and verdict in ("aucun_marqueur", "aucune_reponse"):
        stop_reason = "no_marker"
    if steps == 0 and stop_reason in ("ok", "no_marker"):
        stop_reason = "no_tool_call"

    return {
        "task_id": task["id"],
        "band": task.get("band", f"d{task['min_steps']}"),
        "depth": task.get("depth", task["min_steps"]),
        "min_steps": task["min_steps"],
        "rep": rep,
        "correct": correct,
        "verdict": verdict,
        "answer": answer,
        "expected": task["expected"],
        "steps": steps,
        "decoy_calls": decoy_calls,
        "stop_reason": stop_reason,
        "errors": errors,
        "latency_s": round(time.time() - started, 2),
        "final_text": final_text[:1200],
        "trace": trace,
    }


# --- orchestration ----------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description="Agentic depth benchmark")
    ap.add_argument("--model", default="gemma-4-12b-it-w4a16")
    ap.add_argument("--base-url", default=os.environ.get("VLLM_URL", "http://127.0.0.1:8000/v1"))
    ap.add_argument("--api-key-env", default="VLLM_API_KEY")
    ap.add_argument("--reps", type=int, default=3, help="repetitions per task")
    ap.add_argument("--workers", type=int, default=2, help="keep <= vLLM --max-num-seqs")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--suite", default="v1", choices=["v1", "v2", "v3"])
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--depths", default="", help="v1 only: comma-separated subset, e.g. 1,3")
    ap.add_argument("--bands", default="", help="v2 only: substring filter, e.g. A,C")
    ap.add_argument("--limit", type=int, default=0, help="cap number of tasks (smoke test)")
    ap.add_argument("--tag", default="", help="suffix for output files")
    cfg = ap.parse_args()

    (tasks_all, cfg.tool_schemas, cfg.call_tool, cfg.decoys,
     cfg.system_prompt) = load_suite(cfg.suite)

    cfg.api_key = os.environ.get(cfg.api_key_env, "")
    if not cfg.api_key:
        raise SystemExit(f"{cfg.api_key_env} n'est pas defini dans l'environnement")

    tasks = tasks_all
    if cfg.depths:
        wanted = {int(d) for d in cfg.depths.split(",")}
        tasks = [t for t in tasks if t.get("depth") in wanted]
    if cfg.bands:
        prefixes = tuple(b.strip() for b in cfg.bands.split(","))
        tasks = [t for t in tasks if t.get("band", "").startswith(prefixes)]
    if cfg.limit:
        tasks = tasks[: cfg.limit]

    jobs = [(t, r) for t in tasks for r in range(1, cfg.reps + 1)]
    print(f"suite={cfg.suite}  modele={cfg.model}  outils={len(cfg.tool_schemas)}  "
          f"taches={len(tasks)}  reps={cfg.reps}  runs={len(jobs)}  "
          f"workers={cfg.workers}  temperature={cfg.temperature}")

    results, done = [], 0
    started = time.time()
    with ThreadPoolExecutor(max_workers=cfg.workers) as pool:
        for res in pool.map(lambda j: run_task(j[0], j[1], cfg), jobs):
            results.append(res)
            done += 1
            flag = "OK " if res["correct"] else "KO "
            print(f"[{done:3d}/{len(jobs)}] {flag} {res['task_id']:7s} rep{res['rep']} "
                  f"steps={res['steps']:2d}/{res['min_steps']:<2d} leurres={res['decoy_calls']:2d} "
                  f"{res['verdict']:24s} {res['latency_s']:6.1f}s  rep={str(res['answer'])[:40]!r}",
                  flush=True)

    slug = cfg.model.replace("/", "_")
    suffix = f"-{cfg.suite}" + (f"-{cfg.tag}" if cfg.tag else "")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = os.path.dirname(os.path.abspath(__file__))
    trace_path = os.path.join(base, "traces", f"{slug}{suffix}-{stamp}.jsonl")
    result_path = os.path.join(base, "results", f"{slug}{suffix}-{stamp}.json")

    with open(trace_path, "w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary = {
        "model": cfg.model,
        "suite": cfg.suite,
        "base_url": cfg.base_url,
        "timestamp": stamp,
        "reps": cfg.reps,
        "temperature": cfg.temperature,
        "wall_time_s": round(time.time() - started, 1),
        "runs": [{k: v for k, v in r.items() if k != "trace"} for r in results],
    }
    with open(result_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    print(f"\ntraces  -> {trace_path}\nresultats -> {result_path}")
    os.execvp("python3", ["python3", os.path.join(base, "report.py"), result_path])


if __name__ == "__main__":
    main()
