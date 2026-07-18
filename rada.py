#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RADA MODELI — jeden hub, w którym Twoje agenty AI wspólnie decydują, kto wykona zadanie.

Przepływ (wzorzec Contract Net / "przetarg"):
  1. PRZETARG    — zadanie trafia do wszystkich agentów; każdy składa ofertę (pewność, plan, ryzyka)
  2. GŁOSOWANIE  — agenci widzą ZANONIMIZOWANE oferty i głosują na najlepszą (nie wiedzą, która jest ich)
  3. WYKONANIE   — zwycięzca dostaje zadanie + wspólną pamięć i wykonuje je u siebie
  4. RECENZJA    — (opcjonalnie, --review) wicemistrz sprawdza wynik zwycięzcy

Wspólna pamięć: ./rada_memory/journal.md (skrót dla agentów) + ./rada_memory/runs/*.json (pełne zapisy)

Użycie:
  python3 rada.py "Zrefaktoryzuj moduł płatności i dodaj testy"
  python3 rada.py --mock "cokolwiek"        # symulacja bez zainstalowanych CLI
  python3 rada.py                            # tryb rozmowy (REPL)
  python3 rada.py "@codex napraw testy"      # ręczne ominięcie rady
  python3 rada.py --init                     # zapisz agents.json do edycji
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path


def _configure_utf8_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


# ──────────────────────────────────────────────────────────────────────────────
# KONFIGURACJA AGENTÓW
# W poleceniach "{prompt}" zostaje podmienione na treść zapytania.
# bid_cmd  — tanie zapytanie (oferta / głos), bez uprawnień do zmian
# exec_cmd — właściwe wykonanie zadania (z automatycznym zatwierdzaniem zmian)
# Możesz to nadpisać plikiem agents.json (wygeneruj przez: python3 rada.py --init)
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_AGENTS = {
    "claude": {
        "opis": "Claude Code (Anthropic)",
        "enabled": True,
        "bid_cmd": ["claude", "-p", "{prompt}", "--output-format", "json"],
        "exec_cmd": ["claude", "-p", "{prompt}", "--output-format", "json",
                     "--permission-mode", "acceptEdits"],
    },
    "codex": {
        "opis": "Codex CLI (OpenAI)",
        "enabled": True,
        "bid_cmd": ["codex", "exec", "--skip-git-repo-check", "{prompt}"],
        "exec_cmd": ["codex", "exec", "--skip-git-repo-check",
                     "--sandbox", "workspace-write", "{prompt}"],
    },
    "gemini": {
        "opis": "Gemini CLI (Google)",
        "enabled": True,
        "bid_cmd": ["gemini", "-p", "{prompt}", "--output-format", "json"],
        "exec_cmd": ["gemini", "-p", "{prompt}", "--output-format", "json", "--yolo"],
    },
    "grok": {
        "opis": "Grok Build (xAI)",
        "enabled": True,
        "bid_cmd": ["grok", "-p", "{prompt}", "--output-format", "json"],
        "exec_cmd": ["grok", "-p", "{prompt}", "--output-format", "json", "--always-approve"],
    },
}

VERIFIER_OUTPUT_LIMIT = 4000
VERIFIER_FINAL_STATUS = {
    "PASS": "success",
    "FAIL": "failed",
    "INCONCLUSIVE": "unverified",
}
PROJECT_CONFIG_KEYS = {"verify_cmd", "verify_timeout"}
SAFE_VERIFIER_ENV_KEYS = {
    "COMSPEC", "HOME", "HOMEDRIVE", "HOMEPATH", "LANG", "LC_ALL", "LC_CTYPE",
    "PATH", "PATHEXT", "PYTHONIOENCODING", "PYTHONUTF8", "SYSTEMROOT", "TEMP",
    "TMP", "TMPDIR", "USERPROFILE", "VIRTUAL_ENV", "WINDIR",
}

MEMORY_DIR = Path("rada_memory")
JOURNAL = MEMORY_DIR / "journal.md"
RUNS_DIR = MEMORY_DIR / "runs"
MEMORY_TAIL_CHARS = 4000  # ile znaków wspólnej pamięci dostają agenci

# ──────────────────────────────────────────────────────────────────────────────
# SZABLONY PROMPTÓW (uwaga: literalne klamry JSON są podwojone {{ }})
# ──────────────────────────────────────────────────────────────────────────────

BID_PROMPT = """Jesteś agentem "{agent}" w zespole AI o nazwie Rada Modeli. Do zespołu wpłynęło zadanie.
NIE wykonuj zadania. Oceń jedynie szczerze, jak dobrze TY wykonałbyś je osobiście.

ZADANIE:
{task}

KONTEKST WSPÓLNEJ PAMIĘCI ZESPOŁU (może być pusty):
{memory}

Odpowiedz WYŁĄCZNIE jednym obiektem JSON, bez żadnego tekstu przed ani po:
{{"confidence": <liczba 0-100>, "approach": "<Twój plan w 2-3 zdaniach>", "risks": "<główne ryzyka w 1-2 zdaniach>", "effort": "<S|M|L>"}}"""

VOTE_PROMPT = """Jesteś członkiem rady agentów AI. Rada rozstrzyga, kto wykona zadanie.
Oferty są anonimowe — oceń je wyłącznie merytorycznie (realizm planu, świadomość ryzyk, dopasowanie do zadania).
Deklarowana pewność bywa zawyżona, nie kieruj się nią ślepo.

ZADANIE:
{task}

OFERTY:
{bids_block}

Odpowiedz WYŁĄCZNIE jednym obiektem JSON, bez żadnego tekstu przed ani po:
{{"ranking": [{ids_example}], "why": "<uzasadnienie w 1-2 zdaniach>"}}
Ranking uporządkuj od najlepszej oferty do najsłabszej i użyj dokładnie identyfikatorów ofert."""

EXEC_PROMPT = """Rada agentów AI wybrała Cię w głosowaniu do wykonania zadania.

ZADANIE:
{task}

KONTEKST WSPÓLNEJ PAMIĘCI ZESPOŁU (może być pusty):
{memory}

Wykonaj zadanie najlepiej, jak potrafisz. Na końcu odpowiedzi podaj zwięzłe podsumowanie tego, co zrobiłeś (i wskaż zmienione pliki, jeśli dotyczy)."""

REVIEW_PROMPT = """Jesteś recenzentem w radzie agentów AI. Inny agent wykonał zadanie — sprawdź jego pracę.

ZADANIE:
{task}

RAPORT WYKONAWCY:
{result}

Oceń krytycznie: czy zadanie wygląda na wykonane, czego brakuje, co warto poprawić.
Odpowiedz WYŁĄCZNIE jednym obiektem JSON:
{{"ok": <true|false>, "uwagi": "<2-4 zdania konkretnych uwag>"}}"""

# ──────────────────────────────────────────────────────────────────────────────
# DROBIAZGI: kolory, skróty
# ──────────────────────────────────────────────────────────────────────────────

def _tty() -> bool:
    return sys.stdout.isatty()

def c(txt: str, code: str) -> str:
    return f"\033[{code}m{txt}\033[0m" if _tty() else txt

def bold(t): return c(t, "1")
def dim(t): return c(t, "2")
def green(t): return c(t, "32")
def red(t): return c(t, "31")
def yellow(t): return c(t, "33")
def cyan(t): return c(t, "36")

def short(txt: str, n: int = 110) -> str:
    txt = " ".join(str(txt).split())
    return txt if len(txt) <= n else txt[: n - 1] + "…"

def stable_hash(s: str) -> int:
    return int(hashlib.md5(s.encode("utf-8")).hexdigest(), 16)

# ──────────────────────────────────────────────────────────────────────────────
# PARSOWANIE ODPOWIEDZI
# ──────────────────────────────────────────────────────────────────────────────

ENVELOPE_KEYS = ["result", "response", "message", "content", "text", "final", "output"]

def unwrap_stdout(stdout: str) -> str:
    """CLI potrafią opakować odpowiedź w JSON ({"result": ...}, {"response": ...} itd.).
    Wyciągamy właściwy tekst odpowiedzi modelu."""
    stdout = (stdout or "").strip()
    if not stdout:
        return ""
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return stdout
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for k in ENVELOPE_KEYS:
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                return v
        return stdout
    return stdout

def extract_json_block(text: str):
    """Znajdź pierwszy poprawny obiekt JSON w tekście (modele lubią dodać komentarz)."""
    if not text:
        return None
    depth, start = 0, None
    in_str, esc = False, False  # klamry wewnątrz stringów JSON nie liczą się do zagnieżdżenia
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except (json.JSONDecodeError, ValueError):
                    start = None
    return None

# ──────────────────────────────────────────────────────────────────────────────
# TRYB MOCK — symulacja agentów, żeby przetestować przepływ bez CLI i kluczy
# ──────────────────────────────────────────────────────────────────────────────

MOCK_STYLE = {
    "claude": ("Rozbiję zadanie na kroki: przegląd kontekstu, implementacja, testy, podsumowanie.",
               "Mogę zbyt ostrożnie dobierać zakres zmian."),
    "codex": ("Szybka implementacja w sandboxie, od razu uruchomię testy i poprawię regresje.",
              "Przy słabym opisie zadania mogę źle odgadnąć intencję."),
    "gemini": ("Najpierw research i analiza całego repo, potem plan i dopiero zmiany.",
               "Research może zająć więcej czasu niż samo zadanie."),
    "grok": ("Prosto do celu: minimalny diff, iteracja po pierwszym feedbacku.",
             "Minimalizm może pominąć przypadki brzegowe."),
}

def mock_response(agent: str, phase: str, prompt: str, task: str) -> str:
    h = stable_hash(agent + "|" + task)
    if phase == "bid":
        conf = 55 + h % 41  # 55–95, stabilne dla pary (agent, zadanie)
        approach, risks = MOCK_STYLE.get(agent, ("Wykonam zadanie etapami.", "Brak pełnego kontekstu."))
        effort = ["S", "M", "L"][h % 3]
        return json.dumps({"confidence": conf, "approach": f"[MOCK] {approach}",
                           "risks": risks, "effort": effort}, ensure_ascii=False)
    if phase == "vote":
        found = re.findall(r"\[([A-Z])\][^\n]*?pewność:\s*(\d+)", prompt)
        scored = [(bid_id, int(conf) + (stable_hash(agent + bid_id + task) % 30) - 15)
                  for bid_id, conf in found]
        scored.sort(key=lambda x: -x[1])
        return json.dumps({"ranking": [bid_id for bid_id, _ in scored],
                           "why": f"[MOCK] Głos agenta {agent}: najbardziej przekonujący plan."},
                          ensure_ascii=False)
    if phase == "review":
        return json.dumps({"ok": True, "uwagi": "[MOCK] Wygląda dobrze, warto dodać testy brzegowe."},
                          ensure_ascii=False)
    return (f"[MOCK] Agent {agent} wykonał zadanie: „{short(task, 90)}”.\n"
            f"To symulacja — uruchom bez --mock, gdy masz zainstalowane i zalogowane CLI.")

# ──────────────────────────────────────────────────────────────────────────────
# URUCHAMIANIE AGENTÓW
# ──────────────────────────────────────────────────────────────────────────────

def run_agent(name: str, cfg: dict, phase: str, prompt: str, task: str,
              timeout: int, mock: bool, cwd: str) -> dict:
    """Zwraca: {ok, text, stderr, seconds, error, returncode}."""
    t0 = time.time()
    if mock:
        time.sleep(0.15)
        return {"ok": True, "text": mock_response(name, phase, prompt, task),
                "stderr": "", "seconds": round(time.time() - t0, 2), "error": None,
                "returncode": 0}

    cmd_key = "exec_cmd" if phase == "exec" else "bid_cmd"
    template = None
    try:
        template = cfg.get(cmd_key) or cfg.get("bid_cmd")
        if (not isinstance(template, list) or not template
                or not all(isinstance(part, str) for part in template)):
            raise ValueError(f"{cmd_key} musi być niepustą listą tekstów")
        cmd = [part.replace("{prompt}", prompt) for part in template]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        text = unwrap_stdout(proc.stdout)
        rc = proc.returncode
        # Proces uznajemy za udany TYLKO gdy kod wyjścia == 0 i jest jakiś tekst.
        # Niezerowy kod = błąd, nawet jeśli coś wypisał na stdout (zwykle komunikat błędu).
        ok = (rc == 0) and bool(text.strip())
        if rc != 0:
            err = f"proces zakończył się kodem {rc}"
        elif not text.strip():
            err = "pusty wynik (kod 0)"
        else:
            err = None
        return {"ok": ok, "text": text, "stderr": (proc.stderr or "")[-2000:],
                "seconds": round(time.time() - t0, 2), "error": err, "returncode": rc}
    except subprocess.TimeoutExpired:
        return {"ok": False, "text": "", "stderr": "", "seconds": round(time.time() - t0, 2),
                "error": f"przekroczono limit {timeout}s", "returncode": None}
    except OSError as e:
        error_path = os.path.normcase(os.path.abspath(os.fspath(e.filename))) if e.filename else None
        cwd_path = os.path.normcase(os.path.abspath(os.fspath(cwd)))
        if error_path == cwd_path or not Path(cwd).is_dir():
            error = f"nieprawidłowy katalog roboczy „{cwd}”"
        elif isinstance(e, FileNotFoundError):
            command = template[0] if isinstance(template, list) and template else cmd_key
            error = f"brak polecenia „{command}” w PATH"
        else:
            error = f"błąd uruchomienia procesu: {e}"
        return {"ok": False, "text": "", "stderr": str(e)[-2000:],
                "seconds": round(time.time() - t0, 2), "error": error,
                "returncode": None}
    except Exception as e:  # noqa: BLE001 — prototyp: nie wywracamy całej rady
        return {"ok": False, "text": "", "stderr": str(e)[-2000:],
                "seconds": round(time.time() - t0, 2),
                "error": f"{type(e).__name__}: {e}", "returncode": None}

def run_parallel(agents: dict, phase: str, prompts: dict, task: str,
                 timeout: int, mock: bool, cwd: str) -> dict:
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(agents))) as pool:
        futures = {pool.submit(run_agent, n, cfg, phase, prompts[n], task, timeout, mock, cwd): n
                   for n, cfg in agents.items()}
        for fut in concurrent.futures.as_completed(futures):
            name = futures[fut]
            try:
                results[name] = fut.result()
            except Exception as e:  # noqa: BLE001 — awaria jednego workera nie kończy fazy
                results[name] = {
                    "ok": False, "text": "", "stderr": str(e)[-2000:], "seconds": 0.0,
                    "error": f"{type(e).__name__}: {e}", "returncode": None,
                }
    return results


def _clip_verifier_output(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value)[-VERIFIER_OUTPUT_LIMIT:]


def _verifier_result(status: str, reason: str, started: float,
                     stdout="", stderr="", returncode=None) -> dict:
    return {
        "status": status,
        "reason": reason,
        "stdout": _clip_verifier_output(stdout),
        "stderr": _clip_verifier_output(stderr),
        "seconds": round(time.time() - started, 2),
        "returncode": returncode,
    }


def run_verifier(command, timeout, cwd: str) -> dict:
    """Uruchom lokalny, deterministyczny verifier bez shella i zapisu środowiska."""
    started = time.time()
    if command is None:
        return _verifier_result(
            "INCONCLUSIVE", "no verifier configured", started, returncode=None)
    if (not isinstance(command, list) or not command
            or not all(isinstance(part, str) for part in command)):
        return _verifier_result(
            "INCONCLUSIVE", "invalid verifier configuration: verify_cmd must be a non-empty list of strings",
            started, returncode=None)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        return _verifier_result(
            "INCONCLUSIVE", "invalid verifier configuration: verify_timeout must be positive",
            started, returncode=None)

    try:
        safe_env = {
            key: value for key, value in os.environ.items()
            if key.upper() in SAFE_VERIFIER_ENV_KEYS
        }
        proc = subprocess.run(
            list(command), capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, cwd=cwd, shell=False, env=safe_env)
    except subprocess.TimeoutExpired as e:
        return _verifier_result(
            "INCONCLUSIVE", f"verifier timed out after {timeout}s", started,
            stdout=e.stdout, stderr=e.stderr, returncode=None)
    except OSError as e:
        return _verifier_result(
            "INCONCLUSIVE", f"verifier could not start: {type(e).__name__}: {e}", started,
            stderr=str(e), returncode=None)

    status = "PASS" if proc.returncode == 0 else "FAIL"
    return _verifier_result(
        status, f"exit code {proc.returncode}", started,
        stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)


def attach_verifier(record: dict, opts, execution_attempted: bool = True) -> dict:
    command = getattr(opts, "verify_cmd", None)
    timeout = getattr(opts, "verify_timeout", 300)
    if not execution_attempted and command is not None:
        result = _verifier_result(
            "INCONCLUSIVE", "execution did not run", time.time(), returncode=None)
    else:
        result = run_verifier(command, timeout, getattr(opts, "cwd", "."))
    record["verifier"] = result
    record["final_status"] = VERIFIER_FINAL_STATUS[result["status"]]
    return result


def print_verifier_result(result: dict) -> None:
    colors = {"PASS": green, "FAIL": red, "INCONCLUSIVE": yellow}
    status = result["status"]
    print(bold("\n[verifier] ") + colors[status](status) + dim(f" — {result['reason']}"))

# ──────────────────────────────────────────────────────────────────────────────
# PAMIĘĆ WSPÓLNA
# ──────────────────────────────────────────────────────────────────────────────

def read_memory() -> str:
    if JOURNAL.exists():
        return JOURNAL.read_text(encoding="utf-8")[-MEMORY_TAIL_CHARS:]
    return "(pamięć jest jeszcze pusta)"

def append_memory(task: str, winner: str, tally_txt: str, result: str, run_id: str):
    MEMORY_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = (f"\n## {stamp} — {short(task, 90)}\n"
             f"- Wykonawca: **{winner}** (głosowanie: {tally_txt})\n"
             f"- Wynik: {short(result, 600)}\n"
             f"- Pełny zapis: runs/{run_id}.json\n")
    with JOURNAL.open("a", encoding="utf-8") as f:
        if f.tell() == 0:
            f.write("# Rada Modeli — dziennik wspólnej pamięci\n")
        f.write(entry)

def save_run(run_id: str, payload: dict):
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / f"{run_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

# ──────────────────────────────────────────────────────────────────────────────
# GŁOSOWANIE (Borda) I WYBÓR ZWYCIĘZCY
# ──────────────────────────────────────────────────────────────────────────────

def tally_votes(bid_ids: list, votes: dict) -> dict:
    """votes: {agent: [id1, id2, ...] (od najlepszego)} → punkty Bordy dla każdego id."""
    points = {bid_id: 0 for bid_id in bid_ids}
    n = len(bid_ids)
    for ranking in votes.values():
        # Usuwamy duplikaty zachowując kolejność pierwszego wystąpienia — inaczej
        # głos „A > A > A > A” dałby ofercie A punkty za każdą pozycję (self-stuffing).
        uniq, widziane = [], set()
        for r in ranking:
            if r in points and r not in widziane:
                uniq.append(r)
                widziane.add(r)
        for pos, bid_id in enumerate(uniq):
            points[bid_id] += (n - 1 - pos)
    return points

# ──────────────────────────────────────────────────────────────────────────────
# GŁÓWNY PRZEPŁYW JEDNEGO ZADANIA
# ──────────────────────────────────────────────────────────────────────────────

def council_run(task: str, agents: dict, opts) -> None:
    run_id = uuid.uuid4().hex[:10]
    memory = read_memory()
    record = {"run_id": run_id, "task": task, "started": datetime.now().isoformat(),
              "mock": opts.mock, "routing": "przetarg", "bids": {}, "votes": {},
              "tally": None, "winner": None, "result": None,
              "verifier": None, "review": None, "final_status": "unverified"}

    print(bold(f"\n━━ RADA MODELI ━━  ") + dim(f"(run {run_id}{', MOCK' if opts.mock else ''})"))
    print(f"Zadanie: {cyan(short(task, 200))}\n")

    # ── ręczne ominięcie rady: "@agent zadanie"
    m = re.match(r"^@(\w+)\s+(.+)$", task, re.S)
    if m:
        name, subtask = m.group(1).lower(), m.group(2).strip()
        if name not in agents:
            print(red(f"Nie znam agenta „{name}”. Dostępni: {', '.join(agents)}"))
            return
        print(f"[routing ręczny] wykonuje: {bold(name)}…")
        res = run_agent(name, agents[name], "exec",
                        EXEC_PROMPT.format(task=subtask, memory=memory),
                        subtask, opts.timeout_exec, opts.mock, opts.cwd)
        result_text = res["text"] if res["ok"] else red(f"błąd: {res['error']}")
        print("\n— wynik —\n" + result_text)
        record.update({"routing": "reczny", "winner": name, "result": res,
                       "votes": None, "tally": "routing ręczny"})
        print_verifier_result(attach_verifier(record, opts))
        save_run(run_id, record)
        append_memory(subtask, name, "routing ręczny", res["text"] or str(res["error"]), run_id)
        return

    # ── [1/3] PRZETARG
    print(bold("[1/3] Przetarg") + " — pytam agentów o oferty…")
    bid_prompts = {n: BID_PROMPT.format(agent=n, task=task, memory=memory) for n in agents}
    raw_bids = run_parallel(agents, "bid", bid_prompts, task, opts.timeout_bid, opts.mock, opts.cwd)

    bids = {}
    for name, res in sorted(raw_bids.items()):
        record["bids"][name] = res
        if not res["ok"]:
            print(f"  {red('✗')} {name:<7} {dim('(' + str(res['error']) + ' — pomijam)')}")
            continue
        parsed = extract_json_block(res["text"])
        if not parsed or "confidence" not in parsed:
            print(f"  {yellow('!')} {name:<7} {dim('(nie zwrócił poprawnego JSON — pomijam)')}")
            continue
        try:
            parsed["confidence"] = max(0, min(100, int(parsed.get("confidence", 0))))
        except (TypeError, ValueError):
            parsed["confidence"] = 0
        bids[name] = parsed
        secs = res["seconds"]
        print(f"  {green('✓')} {name:<7} pewność {bold(str(parsed['confidence']))}"
              f"  {dim('(' + str(secs) + 's)')}"
              f"  plan: {short(parsed.get('approach', '—'), 80)}")

    if not bids:
        print(red("\nŻaden agent nie złożył oferty — sprawdź, czy CLI są zainstalowane i zalogowane,"
                  " albo przetestuj przepływ z flagą --mock."))
        print_verifier_result(attach_verifier(record, opts, execution_attempted=False))
        save_run(run_id, record)
        return

    points_by_name = {}
    if len(bids) == 1:
        winner = next(iter(bids))
        tally_txt = "bez głosowania (jedna oferta)"
        print(dim(f"\nTylko jedna ważna oferta — wykonuje {winner}."))
    elif opts.no_vote:
        winner = max(bids, key=lambda n: bids[n]["confidence"])
        tally_txt = "wg pewności (--no-vote)"
        print(dim(f"\n--no-vote: wybieram najwyższą pewność → {winner}."))
    else:
        # ── [2/3] GŁOSOWANIE — oferty anonimizujemy, kolejność losowa (stabilna per run)
        print(bold("\n[2/3] Głosowanie rady") + " — agenci oceniają anonimowe oferty…")
        names = sorted(bids, key=lambda n: stable_hash(run_id + n))
        letters = [chr(ord("A") + i) for i in range(len(names))]
        by_letter = dict(zip(letters, names))
        bids_block = "\n".join(
            f"[{ltr}] pewność: {bids[nm]['confidence']}/100 | nakład: {bids[nm].get('effort', '?')} | "
            f"plan: {short(bids[nm].get('approach', '—'), 220)} | "
            f"ryzyka: {short(bids[nm].get('risks', '—'), 160)}"
            for ltr, nm in by_letter.items())
        ids_example = ", ".join(f'"{l}"' for l in letters)
        vote_prompt = VOTE_PROMPT.format(task=task, bids_block=bids_block, ids_example=ids_example)
        raw_votes = run_parallel(agents, "vote", {n: vote_prompt for n in agents},
                                 task, opts.timeout_bid, opts.mock, opts.cwd)

        votes = {}
        for name, res in sorted(raw_votes.items()):
            record["votes"][name] = res
            parsed = extract_json_block(res["text"]) if res["ok"] else None
            ranking = parsed.get("ranking") if isinstance(parsed, dict) else None
            if isinstance(ranking, list) and ranking:
                ranking = [str(r).strip().upper() for r in ranking]
                votes[name] = ranking
                pretty = " > ".join(by_letter.get(r, r) for r in ranking if r in by_letter)
                print(f"  {green('✓')} {name:<7} głosuje: {pretty}"
                      f"  {dim(short(parsed.get('why', ''), 70))}")
            else:
                print(f"  {yellow('!')} {name:<7} {dim('(głos nieważny)')}")

        points = tally_votes(letters, votes) if votes else {}
        if points and any(points.values()):
            best = max(points.values())
            top = [l for l, p in points.items() if p == best]
            # remis → wyższa deklarowana pewność, potem alfabetycznie
            top.sort(key=lambda l: (-bids[by_letter[l]]["confidence"], l))
            winner = by_letter[top[0]]
            points_by_name = {by_letter[l]: p for l, p in points.items()}
            tally_txt = ", ".join(f"{n} {p} pkt" for n, p in
                                  sorted(points_by_name.items(), key=lambda kv: -kv[1]))
            print(f"\n  Wynik głosowania: {tally_txt}")
        else:
            winner = max(bids, key=lambda n: bids[n]["confidence"])
            tally_txt = "brak ważnych głosów → wg pewności"
            print(yellow("  Brak ważnych głosów — wybieram wg deklarowanej pewności."))

    record["tally"] = tally_txt
    record["winner"] = winner

    # ── [3/3] WYKONANIE
    print(bold(f"\n[3/3] Wykonuje: {winner}") + dim(f"  ({agents[winner].get('opis', '')})") + " …")
    exec_res = run_agent(winner, agents[winner], "exec",
                         EXEC_PROMPT.format(task=task, memory=memory),
                         task, opts.timeout_exec, opts.mock, opts.cwd)
    record["result"] = exec_res
    if exec_res["ok"]:
        print("\n— wynik —\n" + exec_res["text"])
    else:
        print(red(f"\nWykonawca zawiódł: {exec_res['error']}"))

    # ── WERYFIKACJA DETERMINISTYCZNA — jedyne źródło final_status
    print_verifier_result(attach_verifier(record, opts))

    # ── RECENZJA (opcjonalna)
    if opts.review and exec_res["ok"] and len(bids) > 1:
        others = [n for n in bids if n != winner]
        if points_by_name:
            reviewer = max(others, key=lambda n: (points_by_name.get(n, 0),
                                                  bids[n]["confidence"]))
        else:
            reviewer = max(others, key=lambda n: bids[n]["confidence"])
        print(bold(f"\n[recenzja] {reviewer}") + " sprawdza pracę zwycięzcy…")
        rev = run_agent(reviewer, agents[reviewer], "review",
                        REVIEW_PROMPT.format(task=task, result=exec_res["text"][:6000]),
                        task, opts.timeout_bid, opts.mock, opts.cwd)
        parsed = extract_json_block(rev["text"]) if rev["ok"] else None
        record["review"] = {"reviewer": reviewer, "raw": rev, "parsed": parsed}
        if parsed:
            verdict = green("OK") if parsed.get("ok") else yellow("UWAGI")
            print(f"  [{verdict}] {parsed.get('uwagi', '')}")
        else:
            print(dim("  (recenzja nieudana — pomijam)"))

    # ── zapis do pamięci
    save_run(run_id, record)
    append_memory(task, winner, tally_txt,
                  exec_res["text"] if exec_res["ok"] else f"BŁĄD: {exec_res['error']}", run_id)
    print(dim(f"\nZapisano przebieg: {RUNS_DIR}/{run_id}.json  |  pamięć: {JOURNAL}"))

# ──────────────────────────────────────────────────────────────────────────────
# KONFIGURACJA / CLI
# ──────────────────────────────────────────────────────────────────────────────

def load_agents(path: str, only: str) -> dict:
    agents = {k: dict(v) for k, v in DEFAULT_AGENTS.items()}
    p = Path(path)
    if p.exists():
        try:
            user_cfg = json.loads(p.read_text(encoding="utf-8"))
            for name, cfg in user_cfg.items():
                if name.startswith("_") or name in PROJECT_CONFIG_KEYS:
                    continue  # sekcje metadanych (_rules, _uwaga…) — to nie agenci
                if not isinstance(cfg, dict):
                    print(red(f"Pomijam „{name}” w {path}: definicja agenta musi być obiektem."))
                    continue
                agents[name] = {**agents.get(name, {}), **cfg}
        except (json.JSONDecodeError, ValueError) as e:
            print(red(f"Błąd w {path}: {e} — używam konfiguracji domyślnej."))
    agents = {n: cfg for n, cfg in agents.items() if cfg.get("enabled", True)}
    if only:
        wanted = {w.strip().lower() for w in only.split(",") if w.strip()}
        agents = {n: cfg for n, cfg in agents.items() if n in wanted}
    valid_agents = {}
    for name, cfg in agents.items():
        invalid_key = next(
            (key for key in ("bid_cmd", "exec_cmd")
             if not isinstance(cfg.get(key), list) or not cfg[key]
             or not all(isinstance(part, str) for part in cfg[key])),
            None,
        )
        if invalid_key:
            print(red(
                f"Pomijam „{name}” w {path}: {invalid_key} musi być niepustą listą tekstów."
            ))
            continue
        valid_agents[name] = cfg
    return valid_agents


def load_verifier_settings(path: str):
    """Wczytaj ustawienia projektu bez dołączania ich do definicji agentów."""
    p = Path(path)
    if not p.exists():
        return None, 300
    try:
        config = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return None, 300
    if not isinstance(config, dict):
        return None, 300
    return config.get("verify_cmd"), config.get("verify_timeout", 300)


def configure_verifier_options(opts, path: str) -> None:
    config_cmd, config_timeout = load_verifier_settings(path)
    if getattr(opts, "verify_cmd", None) is None:
        opts.verify_cmd = config_cmd
    if getattr(opts, "verify_timeout", None) is None:
        opts.verify_timeout = config_timeout

def main():
    _configure_utf8_stdio()
    ap = argparse.ArgumentParser(
        description="Rada Modeli — Twoje agenty AI wspólnie wybierają, kto wykona zadanie.")
    ap.add_argument("task", nargs="*", help="treść zadania (puste = tryb rozmowy)")
    ap.add_argument("--mock", action="store_true", help="symulacja bez prawdziwych CLI")
    ap.add_argument("--agents", default="agents.json", help="plik konfiguracji agentów")
    ap.add_argument("--only", default="", help="ogranicz radę, np. --only claude,codex")
    ap.add_argument("--no-vote", action="store_true", help="pomiń głosowanie (wygrywa pewność)")
    ap.add_argument("--review", action="store_true", help="wicemistrz recenzuje wynik")
    ap.add_argument("--timeout-bid", type=int, default=300, help="limit [s] na ofertę/głos")
    ap.add_argument("--timeout-exec", type=int, default=3600, help="limit [s] na wykonanie")
    ap.add_argument("--cwd", default=".", help="katalog roboczy dla agentów (projekt)")
    ap.add_argument("--init", action="store_true", help="zapisz agents.json i zakończ")
    ap.add_argument("--verify-timeout", type=int, default=None,
                    help="limit [s] dla deterministycznego verifiera")
    ap.add_argument("--verify-cmd", nargs=argparse.REMAINDER, default=None,
                    help="argv verifiera; ta flaga musi być ostatnia")
    opts = ap.parse_args()

    if opts.init:
        Path("agents.json").write_text(
            json.dumps(DEFAULT_AGENTS, ensure_ascii=False, indent=2), encoding="utf-8")
        print(green("Zapisano agents.json — dostosuj polecenia/model i uruchom ponownie."))
        return

    agents = load_agents(opts.agents, opts.only)
    configure_verifier_options(opts, opts.agents)
    if not agents:
        print(red("Brak włączonych agentów — sprawdź agents.json lub flagę --only."))
        sys.exit(1)

    task = " ".join(opts.task).strip()
    if task:
        council_run(task, agents, opts)
        return

    # tryb rozmowy
    print(bold("Rada Modeli — tryb rozmowy."))
    print(dim(f"Agenci: {', '.join(agents)}. Komendy: :agenci, :pamiec, exit. "
              f"„@nazwa zadanie” omija głosowanie.{'  [MOCK]' if opts.mock else ''}"))
    while True:
        try:
            line = input(cyan("\nrada> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.lower() in {"exit", "quit", "wyjdz", "wyjdź"}:
            break
        if line in {":agenci", ":agents"}:
            for n, cfg in agents.items():
                print(f"  • {n:<7} {dim(cfg.get('opis', ''))}")
            continue
        if line in {":pamiec", ":pamięć", ":memory"}:
            print(read_memory())
            continue
        council_run(line, agents, opts)

if __name__ == "__main__":
    main()
