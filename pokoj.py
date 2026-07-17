#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POKÓJ — czat grupowy Twoich agentów AI (rozszerzenie Rady Modeli).

Jeden wspólny wątek rozmowy, w którym siedzą wszystkie modele. Każda wiadomość ma
podpis "kto → do kogo". Adresat odpowiada, a POZOSTAŁE modele widzą całą wymianę
i mogą wtrącić SPROSTOWANIE (albo spasować). Wszystko zostaje we wspólnym zapisie,
więc każdy model zna pełną historię pokoju.

Reguły przeciw kakofonii (ważne!):
  • wtrącić się można maks. 1 raz na wiadomość, domyślna odpowiedź to PASS
  • na sprostowanie nikt nie odpowiada automatycznie — kolejny ruch należy do Ciebie
  • modele dostają tylko końcówkę zapisu (limit --tail), żeby nie palić tokenów

Użycie:
  python3 pokoj.py --mock                          # symulacja bez CLI
  python3 pokoj.py                                  # tryb rozmowy (REPL)
  python3 pokoj.py "@grok jaka baza do apki z czatem?"   # jedno pytanie i wyjście

W pokoju:
  @grok treść        wiadomość do konkretnego agenta (reszta może się wtrącić)
  treść bez @        pytanie do wszystkich (każdy odpowiada krótko)
  :debata temat      jedna runda dyskusji — każdy zabiera głos po kolei
  :kto  :zapis  exit

Działa na tych samych adapterach co rada.py (musi leżeć w tym samym katalogu).
Aliasy nazw: chatgpt/gpt → codex, grog → grok, google → gemini.
"""

import argparse
import concurrent.futures
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rada  # adaptery CLI, kolory, konfiguracja agentów  # noqa: E402

ALIASES = {
    "chatgpt": "codex", "gpt": "codex", "openai": "codex",
    "grog": "grok", "xai": "grok",
    "google": "gemini", "bard": "gemini",
    "anthropic": "claude",
}

AGENT_COLOR = {"claude": "35", "codex": "32", "gemini": "34", "grok": "33"}

LOG_JSONL = rada.MEMORY_DIR / "pokoj.jsonl"
LOG_MD = rada.MEMORY_DIR / "pokoj.md"

# ──────────────────────────────────────────────────────────────────────────────
# PROMPTY
# ──────────────────────────────────────────────────────────────────────────────

SAY_PROMPT = """Jesteś agentem "{agent}" w pokoju rozmów kilku modeli AI. Uczestnicy: {who}.
Wiadomości mają format "[godzina] nadawca → adresat: treść".

ZAPIS ROZMOWY (końcówka):
{transcript}

Nowa wiadomość od "{sender}", zaadresowana DO CIEBIE:
{msg}

Odpowiedz jako {agent}: rzeczowo, zwięźle (maks. ~200 słów), po polsku.
Napisz samą treść odpowiedzi — bez podpisu i bez cytowania zapisu (podpis doda system)."""

BRIEF_PROMPT = """Jesteś agentem "{agent}" w pokoju rozmów kilku modeli AI. Uczestnicy: {who}.

ZAPIS ROZMOWY (końcówka):
{transcript}

Nowa wiadomość od "{sender}" do WSZYSTKICH:
{msg}

Odpowiedz jako {agent} zwięźle: maks. 3-5 zdań, po polsku, sama treść bez podpisu."""

INTERJECT_PROMPT = """Jesteś agentem "{agent}" w pokoju rozmów kilku modeli AI. Uczestnicy: {who}.

ZAPIS ROZMOWY (końcówka):
{transcript}

Przed chwilą "{responder}" odpowiedział(a) na pytanie od "{sender}":
{response}

Twoja rola: kontrola jakości. Jeśli w tej odpowiedzi widzisz ISTOTNY błąd merytoryczny
albo ważne przemilczane zastrzeżenie — napisz sprostowanie (1-3 zdania, po polsku).
Jeśli odpowiedź jest w porządku albo masz tylko kosmetyczne uwagi, odpowiedz DOKŁADNIE
jednym słowem: PASS"""

DEBATE_PROMPT = """Jesteś agentem "{agent}" w pokoju rozmów kilku modeli AI. Uczestnicy: {who}.
Trwa runda dyskusji na temat: {topic}

ZAPIS ROZMOWY (końcówka, w tym głosy przedmówców w tej rundzie):
{transcript}

Zabierz głos jako {agent}: maks. ~150 słów, po polsku. Odnieś się do przedmówców,
jeśli już mówili (możesz się nie zgodzić). Sama treść, bez podpisu."""

# ──────────────────────────────────────────────────────────────────────────────
# ZAPIS ROZMOWY
# ──────────────────────────────────────────────────────────────────────────────

def append_msg(frm: str, to: str, typ: str, content: str):
    rada.MEMORY_DIR.mkdir(exist_ok=True)
    now = datetime.now()
    entry = {"ts": now.isoformat(timespec="seconds"), "od": frm, "do": to,
             "typ": typ, "tresc": content}
    with LOG_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    label = "SPROSTOWANIE — " if typ == "sprostowanie" else ""
    with LOG_MD.open("a", encoding="utf-8") as f:
        if f.tell() == 0:
            f.write("# Pokój — zapis rozmowy modeli\n\n")
        f.write(f"**[{now.strftime('%Y-%m-%d %H:%M')}] {label}{frm} → {to}:** {content}\n\n")

def transcript_tail(max_chars: int) -> str:
    if not LOG_JSONL.exists():
        return "(pokój jest jeszcze pusty)"
    lines = []
    for raw in LOG_JSONL.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        hhmm = e.get("ts", "")[11:16]
        pre = "SPROSTOWANIE od " if e.get("typ") == "sprostowanie" else ""
        lines.append(f"[{hhmm}] {pre}{e.get('od')} → {e.get('do')}: {e.get('tresc')}")
    text = "\n".join(lines)
    return text[-max_chars:] if len(text) > max_chars else (text or "(pokój jest jeszcze pusty)")

# ──────────────────────────────────────────────────────────────────────────────
# WYPOWIEDZI AGENTÓW (mock albo prawdziwe CLI przez adaptery z rada.py)
# ──────────────────────────────────────────────────────────────────────────────

MOCK_VOICE = {
    "claude": "Uporządkujmy to: najpierw kryteria, potem wybór. Proponuję zacząć od najprostszej opcji, która spełnia wymagania.",
    "codex": "Konkretnie: wziąłbym sprawdzony standard, postawił szkielet i zweryfikował na małym przykładzie jeszcze dziś.",
    "gemini": "Warto spojrzeć szerzej — porównałem podobne przypadki i widzę dwa sensowne warianty zależnie od skali.",
    "grok": "Krótko: nie kombinować. Minimalne rozwiązanie teraz, optymalizacja jak pojawi się realny problem.",
}

def mock_say(agent: str, kind: str, topic: str) -> str:
    h = rada.stable_hash(agent + "|" + kind + "|" + topic)
    if kind == "interject":
        if h % 3:  # ~2/3 przypadków: brak uwag
            return "PASS"
        return (f"[MOCK] Sprostowanie: warto dodać, że przy „{rada.short(topic, 40)}” "
                f"trzeba też uwzględnić przypadek brzegowy, o którym nie wspomniano.")
    base = MOCK_VOICE.get(agent, "Zgadzam się co do zasady, dodałbym jeden warunek.")
    return f"[MOCK] {base} (temat: {rada.short(topic, 60)})"

def say(agent: str, agents: dict, kind: str, prompt: str, topic: str, opts) -> dict:
    """Zwraca {ok, text, error, seconds} — wypowiedź agenta w pokoju."""
    if opts.mock:
        return {"ok": True, "text": mock_say(agent, kind, topic), "error": None, "seconds": 0.1}
    # rozmowa = tanie bid_cmd (bez uprawnień do zmian w plikach)
    return rada.run_agent(agent, agents[agent], "bid", prompt, topic,
                          opts.timeout, False, ".")

def say_parallel(names: list, agents: dict, kind: str, prompts: dict, topic: str, opts) -> dict:
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(names))) as pool:
        futs = {pool.submit(say, n, agents, kind, prompts[n], topic, opts): n for n in names}
        for fut in concurrent.futures.as_completed(futs):
            results[futs[fut]] = fut.result()
    return results

def is_pass(text: str) -> bool:
    t = (text or "").strip().strip('."!»«')
    return t.upper() == "PASS" or (t.upper().startswith("PASS") and len(t) <= 12)

# ──────────────────────────────────────────────────────────────────────────────
# PREZENTACJA
# ──────────────────────────────────────────────────────────────────────────────

def speak(name: str, text: str, typ: str = "odpowiedź"):
    color = AGENT_COLOR.get(name, "36")
    tag = rada.c(f"{name}", "1;" + color)
    prefix = rada.yellow("⚠ sprostowanie od ") if typ == "sprostowanie" else ""
    print(f"\n{prefix}{tag}:")
    print(text.strip())

def resolve_target(word: str, agents: dict):
    w = word.lower().lstrip("@")
    w = ALIASES.get(w, w)
    return w if w in agents else None

# ──────────────────────────────────────────────────────────────────────────────
# OBSŁUGA JEDNEJ WIADOMOŚCI UŻYTKOWNIKA
# ──────────────────────────────────────────────────────────────────────────────

def handle_message(text: str, agents: dict, opts):
    who = ", ".join(list(agents) + [opts.nick])
    m = re.match(r"^@(\S+)\s+(.+)$", text, re.S)

    # ── wiadomość zaadresowana: odpowiada adresat, reszta może się wtrącić
    if m:
        target = resolve_target(m.group(1), agents)
        if not target:
            print(rada.red(f"Nie znam agenta „{m.group(1)}”. Dostępni: {', '.join(agents)} "
                           f"(aliasy: {', '.join(sorted(ALIASES))})"))
            return
        msg = m.group(2).strip()
        append_msg(opts.nick, target, "wiadomosc", msg)
        tail = transcript_tail(opts.tail)

        res = say(target, agents, "say",
                  SAY_PROMPT.format(agent=target, who=who, transcript=tail,
                                    sender=opts.nick, msg=msg), msg, opts)
        if not res["ok"]:
            print(rada.red(f"{target} nie odpowiada: {res['error']}"))
            return
        speak(target, res["text"])
        append_msg(target, opts.nick, "odpowiedz", res["text"].strip())

        if opts.no_sprostowania:
            return
        others = [n for n in agents if n != target]
        if not others:
            return
        print(rada.dim(f"\n… pozostali ({', '.join(others)}) czytają odpowiedź i mogą się wtrącić …"))
        tail = transcript_tail(opts.tail)
        prompts = {n: INTERJECT_PROMPT.format(agent=n, who=who, transcript=tail,
                                              responder=target, sender=opts.nick,
                                              response=res["text"][:4000])
                   for n in others}
        inter = say_parallel(others, agents, "interject", prompts, msg, opts)
        quiet = True
        for n in others:
            r = inter.get(n, {})
            if r.get("ok") and not is_pass(r["text"]):
                quiet = False
                speak(n, r["text"], typ="sprostowanie")
                append_msg(n, target, "sprostowanie", r["text"].strip())
        if quiet:
            print(rada.dim("  (nikt nie zgłosił uwag — wszyscy: PASS)"))
        return

    # ── wiadomość do wszystkich: każdy odpowiada krótko
    append_msg(opts.nick, "wszyscy", "wiadomosc", text)
    tail = transcript_tail(opts.tail)
    prompts = {n: BRIEF_PROMPT.format(agent=n, who=who, transcript=tail,
                                      sender=opts.nick, msg=text) for n in agents}
    print(rada.dim(f"… pytam wszystkich ({', '.join(agents)}) …"))
    results = say_parallel(list(agents), agents, "say", prompts, text, opts)
    for n in agents:
        r = results.get(n, {})
        if r.get("ok"):
            speak(n, r["text"])
            append_msg(n, "wszyscy", "odpowiedz", r["text"].strip())
        else:
            print(rada.dim(f"\n({n} niedostępny: {r.get('error')})"))

# ──────────────────────────────────────────────────────────────────────────────
# RUNDA DEBATY
# ──────────────────────────────────────────────────────────────────────────────

def debate(topic: str, agents: dict, opts, rounds: int = 1):
    who = ", ".join(list(agents) + [opts.nick])
    append_msg(opts.nick, "wszyscy", "wiadomosc", f"[debata] {topic}")
    for rnd in range(rounds):
        for name in agents:  # sekwencyjnie — każdy widzi przedmówców
            tail = transcript_tail(opts.tail)
            res = say(name, agents, "say",
                      DEBATE_PROMPT.format(agent=name, who=who, transcript=tail, topic=topic),
                      topic, opts)
            if res["ok"]:
                speak(name, res["text"])
                append_msg(name, "wszyscy", "odpowiedz", res["text"].strip())
            else:
                print(rada.dim(f"({name} niedostępny: {res.get('error')})"))

# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Pokój — czat grupowy Twoich agentów AI.")
    ap.add_argument("message", nargs="*", help="jedna wiadomość (puste = tryb rozmowy)")
    ap.add_argument("--mock", action="store_true", help="symulacja bez prawdziwych CLI")
    ap.add_argument("--agents", default="agents.json", help="plik konfiguracji agentów")
    ap.add_argument("--only", default="", help="ogranicz skład, np. --only claude,codex")
    ap.add_argument("--nick", default="szef", help="Twój podpis w zapisie (domyślnie: szef)")
    ap.add_argument("--tail", type=int, default=6000, help="ile znaków historii dostają modele")
    ap.add_argument("--timeout", type=int, default=300, help="limit [s] na wypowiedź")
    ap.add_argument("--no-sprostowania", action="store_true",
                    help="wyłącz rundę wtrąceń po odpowiedzi adresata")
    opts = ap.parse_args()

    agents = rada.load_agents(opts.agents, opts.only)
    if not agents:
        print(rada.red("Brak włączonych agentów — sprawdź agents.json lub flagę --only."))
        sys.exit(1)

    one_shot = " ".join(opts.message).strip()
    if one_shot:
        handle_message(one_shot, agents, opts)
        return

    print(rada.bold("Pokój — czat grupowy modeli.") +
          rada.dim(f"  Uczestnicy: {', '.join(agents)} + {opts.nick}."
                   f"{'  [MOCK]' if opts.mock else ''}"))
    print(rada.dim("„@grok pytanie” → adresat odpowiada, reszta może wtrącić sprostowanie. "
                   "Bez @ → odpowiadają wszyscy. Komendy: :debata temat, :kto, :zapis, exit."))
    while True:
        try:
            line = input(rada.cyan(f"\n{opts.nick}> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.lower() in {"exit", "quit", "wyjdz", "wyjdź"}:
            break
        if line in {":kto", ":agenci"}:
            for n, cfg in agents.items():
                print(f"  • {n:<7} {rada.dim(cfg.get('opis', ''))}")
            continue
        if line in {":zapis", ":pamiec", ":pamięć"}:
            print(transcript_tail(opts.tail))
            continue
        if line.startswith(":debata"):
            topic = line[len(":debata"):].strip()
            if topic:
                debate(topic, agents, opts)
            else:
                print(rada.red("Podaj temat: :debata monorepo czy multirepo?"))
            continue
        handle_message(line, agents, opts)

if __name__ == "__main__":
    main()
