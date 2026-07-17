#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WEB — komunikator w przeglądarce dla Twoich agentów AI (nakładka na pokój).

Odpala lokalny serwer i otwiera czat grupowy jak w komunikatorze: dymki, awatary,
podpisy "kto → do kogo", sprostowania z ostrzeżeniem i wskaźnik "pisze…".
Backend jest ten sam co w pokoj.py (adaptery CLI z rada.py) — zero zależności,
sam Python. Zapis rozmowy współdzielony z pokojem: rada_memory/pokoj.jsonl.

Użycie:
  python3 web.py --mock          # symulacja bez CLI (do obejrzenia interfejsu)
  python3 web.py                 # na żywych agentach
  python3 web.py --port 8787 --only claude,codex --no-open

W czacie:
  @grok pytanie      → odpowiada Grok, reszta może wtrącić sprostowanie
  pytanie bez @      → odpowiadają wszyscy (panel)
  :debata temat      → runda dyskusji modeli między sobą
"""

import argparse
import json
import re
import sys
import threading
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rada   # noqa: E402
import pokoj  # noqa: E402

OPTS = None
AGENTS = {}
STATE = {"busy": False, "status": ""}
LOCK = threading.Lock()

def set_status(txt: str):
    with LOCK:
        STATE["status"] = txt

def read_messages(since: int = 0):
    if not pokoj.LOG_JSONL.exists():
        return [], 0
    lines = pokoj.LOG_JSONL.read_text(encoding="utf-8").splitlines()
    out = []
    for raw in lines[since:]:
        try:
            out.append(json.loads(raw))
        except (json.JSONDecodeError, ValueError):
            continue
    return out, len(lines)

# ──────────────────────────────────────────────────────────────────────────────
# PRZETWARZANIE WIADOMOŚCI (w tle, wyniki lądują w pokoj.jsonl)
# ──────────────────────────────────────────────────────────────────────────────

def process(text: str):
    agents, opts = AGENTS, OPTS
    who = ", ".join(list(agents) + [opts.nick])
    try:
        # ── przetarg rady (pełny przebieg: oferty → głosy → wykonanie → recenzja)
        if text.startswith(":rada"):
            zadanie = text[len(":rada"):].strip()
            if not zadanie:
                pokoj.append_msg("system", opts.nick, "system",
                                 "Podaj zadanie: „:rada opisz, co ma zostać zrobione”")
                return
            process_rada(zadanie)
            return

        # ── debata
        if text.startswith(":debata"):
            topic = text[len(":debata"):].strip()
            if not topic:
                pokoj.append_msg("system", opts.nick, "system",
                                 "Podaj temat, np. „:debata monorepo czy multirepo?”")
                return
            pokoj.append_msg(opts.nick, "wszyscy", "wiadomosc", f"[debata] {topic}")
            for name in agents:
                set_status(f"{name} zabiera głos…")
                tail = pokoj.transcript_tail(opts.tail)
                res = pokoj.say(name, agents, "say",
                                pokoj.DEBATE_PROMPT.format(agent=name, who=who,
                                                           transcript=tail, topic=topic),
                                topic, opts)
                if res["ok"]:
                    pokoj.append_msg(name, "wszyscy", "odpowiedz", res["text"].strip())
                else:
                    pokoj.append_msg("system", "wszyscy", "system",
                                     f"{name} niedostępny: {res.get('error')}")
            return

        # ── wiadomość zaadresowana
        m = re.match(r"^@(\S+)\s+(.+)$", text, re.S)
        if m:
            target = pokoj.resolve_target(m.group(1), agents)
            if not target:
                pokoj.append_msg("system", opts.nick, "system",
                                 f"Nie znam agenta „{m.group(1)}”. "
                                 f"Dostępni: {', '.join(agents)}")
                return
            msg = m.group(2).strip()
            pokoj.append_msg(opts.nick, target, "wiadomosc", msg)
            set_status(f"{target} pisze…")
            tail = pokoj.transcript_tail(opts.tail)
            res = pokoj.say(target, agents, "say",
                            pokoj.SAY_PROMPT.format(agent=target, who=who, transcript=tail,
                                                    sender=opts.nick, msg=msg), msg, opts)
            if not res["ok"]:
                pokoj.append_msg("system", opts.nick, "system",
                                 f"{target} nie odpowiada: {res.get('error')}")
                return
            pokoj.append_msg(target, opts.nick, "odpowiedz", res["text"].strip())

            if opts.no_sprostowania:
                return
            others = [n for n in agents if n != target]
            if not others:
                return
            set_status("pozostali sprawdzają odpowiedź…")
            tail = pokoj.transcript_tail(opts.tail)
            prompts = {n: pokoj.INTERJECT_PROMPT.format(agent=n, who=who, transcript=tail,
                                                        responder=target, sender=opts.nick,
                                                        response=res["text"][:4000])
                       for n in others}
            inter = pokoj.say_parallel(others, agents, "interject", prompts, msg, opts)
            passes = []
            for n in others:
                r = inter.get(n, {})
                if r.get("ok") and not pokoj.is_pass(r["text"]):
                    pokoj.append_msg(n, target, "sprostowanie", r["text"].strip())
                else:
                    passes.append(n)
            if passes:
                pokoj.append_msg("system", "wszyscy", "system",
                                 "bez uwag (PASS): " + ", ".join(passes))
            return

        # ── wiadomość do wszystkich
        pokoj.append_msg(opts.nick, "wszyscy", "wiadomosc", text)
        set_status("wszyscy piszą…")
        tail = pokoj.transcript_tail(opts.tail)
        prompts = {n: pokoj.BRIEF_PROMPT.format(agent=n, who=who, transcript=tail,
                                                sender=opts.nick, msg=text) for n in agents}
        results = pokoj.say_parallel(list(agents), agents, "say", prompts, text, opts)
        for n in agents:
            r = results.get(n, {})
            if r.get("ok"):
                pokoj.append_msg(n, "wszyscy", "odpowiedz", r["text"].strip())
            else:
                pokoj.append_msg("system", "wszyscy", "system",
                                 f"{n} niedostępny: {r.get('error')}")
    finally:
        with LOCK:
            STATE["busy"] = False
            STATE["status"] = ""

# ──────────────────────────────────────────────────────────────────────────────
# PRZETARG RADY W PRZEGLĄDARCE (karta przebiegu: oferty → głosy → wykonanie → recenzja)
# ──────────────────────────────────────────────────────────────────────────────

def process_rada(task: str):
    agents, opts = AGENTS, OPTS
    run_id = uuid.uuid4().hex[:10]
    memory = rada.read_memory()
    pokoj.append_msg(opts.nick, "rada", "wiadomosc", task)
    record = {"run_id": run_id, "task": task, "started": datetime.now().isoformat(),
              "mock": opts.mock, "source": "web", "bids": {}, "votes": {},
              "mapping": {}, "tally": None, "winner": None, "result": None, "review": None}

    # ── [1] PRZETARG: oferty od wszystkich
    set_status("rada: zbieram oferty…")
    prompts = {n: rada.BID_PROMPT.format(agent=n, task=task, memory=memory) for n in agents}
    raw = rada.run_parallel(agents, "bid", prompts, task, opts.timeout, opts.mock, ".")
    bids = {}
    for n in sorted(raw):
        r = raw[n]
        record["bids"][n] = r
        parsed = rada.extract_json_block(r["text"]) if r["ok"] else None
        if parsed and "confidence" in parsed:
            try:
                parsed["confidence"] = max(0, min(100, int(parsed["confidence"])))
            except (TypeError, ValueError):
                parsed["confidence"] = 0
            bids[n] = parsed
            pokoj.append_msg(n, "rada", "oferta", json.dumps({
                "confidence": parsed["confidence"],
                "approach": str(parsed.get("approach", ""))[:400],
                "risks": str(parsed.get("risks", ""))[:300],
                "effort": str(parsed.get("effort", "?"))[:3],
            }, ensure_ascii=False))
        else:
            pokoj.append_msg("system", "rada", "system",
                             f"{n}: oferta odrzucona ({r.get('error') or 'niepoprawny JSON'})")
    if not bids:
        pokoj.append_msg("system", opts.nick, "system",
                         "Rada nie zebrała żadnej ważnej oferty — sprawdź CLI albo użyj --mock.")
        rada.save_run(run_id, record)
        return

    # ── [2] GŁOSOWANIE na anonimowe oferty
    points_by_name = {}
    if len(bids) == 1:
        winner = next(iter(bids))
        tally_txt = "bez głosowania (jedna oferta)"
        pokoj.append_msg("system", "rada", "system", f"Tylko jedna ważna oferta — wykonuje {winner}.")
    else:
        set_status("rada: głosowanie…")
        names = sorted(bids, key=lambda n: rada.stable_hash(run_id + n))
        letters = [chr(ord("A") + i) for i in range(len(names))]
        by_letter = dict(zip(letters, names))
        record["mapping"] = by_letter
        bids_block = "\n".join(
            f"[{l}] pewność: {bids[nm]['confidence']}/100 | nakład: {bids[nm].get('effort', '?')} | "
            f"plan: {rada.short(bids[nm].get('approach', '—'), 220)} | "
            f"ryzyka: {rada.short(bids[nm].get('risks', '—'), 160)}"
            for l, nm in by_letter.items())
        ids_example = ", ".join(f'"{l}"' for l in letters)
        vp = rada.VOTE_PROMPT.format(task=task, bids_block=bids_block, ids_example=ids_example)
        raw_votes = rada.run_parallel(agents, "vote", {n: vp for n in agents},
                                      task, opts.timeout, opts.mock, ".")
        votes = {}
        for n in sorted(raw_votes):
            rv = raw_votes[n]
            record["votes"][n] = rv
            pv = rada.extract_json_block(rv["text"]) if rv["ok"] else None
            ranking = pv.get("ranking") if isinstance(pv, dict) else None
            if isinstance(ranking, list) and ranking:
                ranking = [str(x).strip().upper() for x in ranking]
                votes[n] = ranking
                pokoj.append_msg(n, "rada", "glos", json.dumps({
                    "ranking": [by_letter.get(x, x) for x in ranking if x in by_letter],
                    "why": str(pv.get("why", ""))[:200]}, ensure_ascii=False))
            else:
                pokoj.append_msg("system", "rada", "system", f"{n}: głos nieważny")
        points = rada.tally_votes(letters, votes) if votes else {}
        if points and any(points.values()):
            best = max(points.values())
            top = sorted([l for l, p in points.items() if p == best],
                         key=lambda l: (-bids[by_letter[l]]["confidence"], l))
            winner = by_letter[top[0]]
            points_by_name = {by_letter[l]: p for l, p in points.items()}
            tally_txt = ", ".join(f"{n} {p} pkt" for n, p in
                                  sorted(points_by_name.items(), key=lambda kv: -kv[1]))
        else:
            winner = max(bids, key=lambda n: bids[n]["confidence"])
            tally_txt = "brak ważnych głosów → wg pewności"
        pokoj.append_msg("system", "rada", "tally", json.dumps({
            "points": points_by_name, "winner": winner, "note": tally_txt}, ensure_ascii=False))
    record["tally"] = tally_txt
    record["winner"] = winner

    # ── [3] WYKONANIE przez zwycięzcę
    set_status(f"rada: wykonuje {winner}…")
    er = rada.run_agent(winner, agents[winner], "exec",
                        rada.EXEC_PROMPT.format(task=task, memory=memory),
                        task, opts.timeout_exec, opts.mock, ".")
    record["result"] = er
    if er["ok"]:
        pokoj.append_msg(winner, "rada", "wykonanie", er["text"].strip())
    else:
        pokoj.append_msg("system", "rada", "system",
                         f"Wykonawca {winner} zawiódł: {er.get('error')}")

    # ── [4] RECENZJA — wicemistrz WEDŁUG GŁOSOWANIA (nie samooceny)
    others = [n for n in bids if n != winner]
    if er["ok"] and others:
        if points_by_name:
            reviewer = max(others, key=lambda n: (points_by_name.get(n, 0),
                                                  bids[n]["confidence"]))
        else:
            reviewer = max(others, key=lambda n: bids[n]["confidence"])
        set_status(f"rada: recenzja ({reviewer})…")
        rr = rada.run_agent(reviewer, agents[reviewer], "review",
                            rada.REVIEW_PROMPT.format(task=task, result=er["text"][:6000]),
                            task, opts.timeout, opts.mock, ".")
        pr = rada.extract_json_block(rr["text"]) if rr["ok"] else None
        record["review"] = {"reviewer": reviewer, "raw": rr, "parsed": pr}
        if pr:
            pokoj.append_msg(reviewer, winner, "recenzja", json.dumps(
                {"ok": bool(pr.get("ok")), "uwagi": str(pr.get("uwagi", ""))[:400]},
                ensure_ascii=False))
        else:
            pokoj.append_msg("system", "rada", "system", f"recenzja od {reviewer} nieudana")

    rada.save_run(run_id, record)
    rada.append_memory(task, winner, tally_txt,
                       er["text"] if er["ok"] else f"BŁĄD: {er.get('error')}", run_id)
    pokoj.append_msg("system", "rada", "system", f"Pełny zapis przebiegu: runs/{run_id}.json")

# ──────────────────────────────────────────────────────────────────────────────
# SERWER HTTP
# ──────────────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # cisza w konsoli
        pass

    def _json(self, code: int, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif url.path == "/api/messages":
            since = 0
            try:
                since = int(parse_qs(url.query).get("since", ["0"])[0])
            except (TypeError, ValueError):
                pass
            msgs, total = read_messages(since)
            with LOCK:
                busy, status = STATE["busy"], STATE["status"]
            self._json(200, {"messages": msgs, "total": total, "busy": busy,
                             "status": status, "nick": OPTS.nick, "agents": list(AGENTS),
                             "mock": OPTS.mock})
        else:
            self._json(404, {"error": "nie ma takiej ścieżki"})

    def do_POST(self):
        if urlparse(self.path).path != "/api/send":
            return self._json(404, {"error": "nie ma takiej ścieżki"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (json.JSONDecodeError, ValueError):
            return self._json(400, {"error": "niepoprawny JSON"})
        text = (data.get("text") or "").strip()
        if not text:
            return self._json(400, {"error": "pusta wiadomość"})
        with LOCK:
            if STATE["busy"]:
                return self._json(409, {"error": "modele jeszcze piszą — chwila"})
            STATE["busy"] = True
            STATE["status"] = "wysyłam…"
        threading.Thread(target=process, args=(text,), daemon=True).start()
        self._json(202, {"ok": True})

# ──────────────────────────────────────────────────────────────────────────────
# STRONA (komunikator)
# ──────────────────────────────────────────────────────────────────────────────

PAGE = """<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pokój — komunikator modeli</title>
<style>
  :root{
    --bg:#0e1116; --panel:#161b22; --bubble:#1d242e; --me:#2456c8;
    --text:#e8eaee; --dim:#8b95a3; --line:#232b36; --warn:#e8c34f;
  }
  *{box-sizing:border-box} html,body{height:100%}
  body{margin:0;background:var(--bg);color:var(--text);
       font:15px/1.45 -apple-system,'Segoe UI',Roboto,Ubuntu,sans-serif;
       display:flex;flex-direction:column}
  header{padding:12px 16px;background:var(--panel);border-bottom:1px solid var(--line);
         display:flex;align-items:center;gap:10px;flex-wrap:wrap}
  header h1{font-size:16px;margin:0;font-weight:700}
  header .who{display:flex;gap:6px;flex-wrap:wrap}
  .pill{font-size:11px;padding:3px 9px;border-radius:99px;background:var(--bubble);
        color:var(--dim);border:1px solid var(--line)}
  .pill b{color:var(--text)}
  #mockbadge{color:var(--warn);border-color:var(--warn)}
  main{flex:1;overflow-y:auto;padding:14px 12px 6px;display:flex;flex-direction:column;gap:10px}
  .row{display:flex;gap:8px;align-items:flex-end;max-width:92%}
  .row.me{align-self:flex-end;flex-direction:row-reverse}
  .avatar{width:34px;height:34px;border-radius:50%;flex:0 0 34px;display:flex;
          align-items:center;justify-content:center;font-size:12px;font-weight:800;color:#0d1117}
  .stack{display:flex;flex-direction:column;gap:3px;min-width:0}
  .meta{font-size:11px;color:var(--dim);padding:0 6px}
  .row.me .meta{text-align:right}
  .bubble{background:var(--bubble);padding:9px 12px;border-radius:14px;border-bottom-left-radius:4px;
          white-space:pre-wrap;word-wrap:break-word;border:1px solid var(--line)}
  .row.me .bubble{background:var(--me);border-color:transparent;
                  border-radius:14px;border-bottom-right-radius:4px}
  .row.spr .bubble{border-color:var(--warn);box-shadow:inset 3px 0 0 var(--warn)}
  .spr-label{color:var(--warn);font-weight:700}
  .sys{align-self:center;font-size:12px;color:var(--dim);background:var(--panel);
       border:1px dashed var(--line);padding:4px 12px;border-radius:99px;max-width:88%;text-align:center}
  .bidcard{min-width:240px}
  .bidtop{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-bottom:4px}
  .bar{height:6px;background:#0b0e12;border-radius:99px;overflow:hidden;margin:4px 0 8px}
  .bar i{display:block;height:100%;border-radius:99px}
  .risks{color:var(--dim);font-size:12.5px;margin-top:6px}
  .vote{align-self:flex-start;text-align:left;max-width:96%;border-style:solid}
  .tallycard{align-self:center;background:var(--panel);border:1px solid var(--line);
             border-radius:14px;padding:10px 18px 12px;min-width:250px}
  .trow{display:flex;justify-content:space-between;gap:20px;padding:3px 0;color:var(--dim)}
  .trow.win{color:var(--text);font-weight:700}
  #typing{min-height:22px;padding:2px 18px;font-size:12.5px;color:var(--dim);font-style:italic}
  #typing .dots::after{content:'…';animation:d 1.2s infinite}
  @keyframes d{0%{content:'.'}33%{content:'..'}66%{content:'…'}}
  footer{background:var(--panel);border-top:1px solid var(--line);padding:8px 10px 12px}
  .chips{display:flex;gap:6px;overflow-x:auto;padding-bottom:8px}
  .chip{font-size:12px;padding:4px 10px;border-radius:99px;background:var(--bubble);
        color:var(--text);border:1px solid var(--line);cursor:pointer;white-space:nowrap}
  .chip:hover{border-color:var(--dim)}
  .composer{display:flex;gap:8px}
  #inp{flex:1;background:var(--bubble);border:1px solid var(--line);border-radius:12px;
       color:var(--text);padding:11px 13px;font-size:15px;outline:none}
  #inp:focus{border-color:#3a6ad4}
  #send{background:var(--me);border:0;border-radius:12px;color:#fff;font-weight:700;
        padding:0 18px;font-size:15px;cursor:pointer}
  #send:disabled{opacity:.45;cursor:default}
  #toast{position:fixed;left:50%;transform:translateX(-50%);bottom:86px;background:#2a1e1e;
         color:#f2b8b5;border:1px solid #5c3535;padding:8px 14px;border-radius:10px;
         font-size:13px;display:none;z-index:9}
</style>
</head>
<body>
<header>
  <h1>💬 Pokój — komunikator modeli</h1>
  <div class="who" id="who"></div>
</header>
<main id="chat"></main>
<div id="typing"></div>
<footer>
  <div class="chips" id="chips"></div>
  <div class="composer">
    <input id="inp" placeholder="Napisz… (:rada zadanie = przetarg, @grok pytanie, bez @ do wszystkich)" autocomplete="off">
    <button id="send">Wyślij</button>
  </div>
</footer>
<div id="toast"></div>
<script>
const COLORS = {claude:'#b48ce8', codex:'#5fc98f', gemini:'#6ba3f7', grok:'#e8c34f'};
const chat = document.getElementById('chat');
const typing = document.getElementById('typing');
const inp = document.getElementById('inp');
const send = document.getElementById('send');
let since = 0, nick = 'szef', agents = [];

function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML;}
function initials(n){return n==='codex' ? 'GPT' : n.slice(0,2).toUpperCase();}
function toast(msg){const t=document.getElementById('toast');t.textContent=msg;
  t.style.display='block';setTimeout(()=>t.style.display='none',2600);}

function pj(s){ try{ return JSON.parse(s); }catch(err){ return null; } }

function addMsg(e){
  const time = (e.ts||'').slice(11,16);
  const acolor = COLORS[e.od] || '#9aa3ad';

  if(e.typ === 'oferta'){
    const b = pj(e.tresc) || {};
    const row = document.createElement('div'); row.className = 'row';
    row.innerHTML = '<div class="avatar" style="background:'+acolor+'">'+esc(initials(e.od))+'</div>'+
      '<div class="stack"><div class="meta">oferta · '+esc(e.od)+' · '+time+'</div>'+
      '<div class="bubble bidcard">'+
      '<div class="bidtop"><b>pewność '+(b.confidence!=null?b.confidence:'?')+'/100</b>'+
      '<span class="pill">nakład: '+esc(b.effort||'?')+'</span></div>'+
      '<div class="bar"><i style="width:'+(b.confidence||0)+'%;background:'+acolor+'"></i></div>'+
      '<div>'+esc(b.approach||'')+'</div>'+
      (b.risks ? '<div class="risks">⚠ '+esc(b.risks)+'</div>' : '')+
      '</div></div>';
    chat.appendChild(row); return;
  }
  if(e.typ === 'glos'){
    const v = pj(e.tresc) || {};
    const d = document.createElement('div'); d.className = 'sys vote';
    d.innerHTML = '🗳 <b style="color:'+acolor+'">'+esc(e.od)+'</b> głosuje: '+
      esc((v.ranking||[]).join(' → '))+
      (v.why ? ' <span style="opacity:.65">· '+esc(v.why)+'</span>' : '');
    chat.appendChild(d); return;
  }
  if(e.typ === 'tally'){
    const t = pj(e.tresc) || {};
    const entries = Object.entries(t.points||{}).sort((a,b)=>b[1]-a[1]);
    const d = document.createElement('div'); d.className = 'tallycard';
    d.innerHTML = '<div class="meta" style="text-align:center;margin-bottom:4px">wynik głosowania · '+time+'</div>'+
      (entries.length
        ? entries.map(([n,p])=>'<div class="trow'+(n===t.winner?' win':'')+'">'+
            '<span>'+(n===t.winner?'🏆 ':'')+'<b style="color:'+(COLORS[n]||'#9aa3ad')+'">'+esc(n)+'</b></span>'+
            '<span>'+p+' pkt</span></div>').join('')
        : '<div class="trow"><span>'+esc(t.note||'')+'</span></div>');
    chat.appendChild(d); return;
  }
  if(e.typ === 'wykonanie'){
    const row = document.createElement('div'); row.className = 'row';
    row.innerHTML = '<div class="avatar" style="background:'+acolor+'">'+esc(initials(e.od))+'</div>'+
      '<div class="stack"><div class="meta">🏆 wykonawca · '+esc(e.od)+' · '+time+'</div>'+
      '<div class="bubble" style="border-color:'+acolor+'">'+esc(e.tresc)+'</div></div>';
    chat.appendChild(row); return;
  }
  if(e.typ === 'recenzja'){
    const r = pj(e.tresc) || {};
    const row = document.createElement('div'); row.className = 'row'+(r.ok?'':' spr');
    row.innerHTML = '<div class="avatar" style="background:'+acolor+'">'+esc(initials(e.od))+'</div>'+
      '<div class="stack"><div class="meta">recenzja · '+esc(e.od)+' → '+esc(e.do)+' · '+time+'</div>'+
      '<div class="bubble">'+(r.ok?'✅ ':'⚠ ')+esc(r.uwagi||'')+'</div></div>';
    chat.appendChild(row); return;
  }

  if(e.od === 'system' || e.typ === 'system'){
    const d = document.createElement('div'); d.className = 'sys';
    d.innerHTML = esc(e.tresc) + ' <span style="opacity:.6">· ' + time + '</span>';
    chat.appendChild(d); return;
  }
  const mine = (e.od === nick);
  const row = document.createElement('div');
  row.className = 'row' + (mine ? ' me' : '') + (e.typ === 'sprostowanie' ? ' spr' : '');
  const color = COLORS[e.od] || '#9aa3ad';
  let inner = '';
  if(!mine){
    inner += '<div class="avatar" style="background:' + color + '">' + esc(initials(e.od)) + '</div>';
  }
  const label = e.typ === 'sprostowanie'
      ? '<span class="spr-label">⚠ sprostowanie</span> · ' + esc(e.od) + ' → ' + esc(e.do)
      : esc(e.od) + ' → ' + esc(e.do);
  inner += '<div class="stack"><div class="meta">' + label + ' · ' + time + '</div>' +
           '<div class="bubble">' + esc(e.tresc) + '</div></div>';
  row.innerHTML = inner;
  chat.appendChild(row);
}

async function poll(){
  try{
    const r = await fetch('/api/messages?since=' + since);
    const d = await r.json();
    nick = d.nick;
    if(agents.length !== d.agents.length){
      agents = d.agents;
      document.getElementById('who').innerHTML =
        d.agents.map(a=>'<span class="pill" style="border-color:'+(COLORS[a]||'#333')+'"><b>'+esc(a)+'</b></span>').join('') +
        '<span class="pill">Ty: <b>'+esc(d.nick)+'</b></span>' +
        (d.mock ? '<span class="pill" id="mockbadge">MOCK</span>' : '');
      const chips = [':rada '].concat(['wszyscy']).concat(d.agents.map(a=>'@'+a)).concat([':debata ']);
      document.getElementById('chips').innerHTML =
        chips.map(c=>'<span class="chip">'+esc(c)+'</span>').join('');
      document.querySelectorAll('.chip').forEach(ch=>ch.onclick=()=>{
        inp.value = ch.textContent === 'wszyscy' ? '' : ch.textContent + (ch.textContent.startsWith('@')?' ':'');
        inp.focus();
      });
    }
    if(d.messages.length){
      d.messages.forEach(addMsg);
      since = d.total;
      chat.scrollTop = chat.scrollHeight;
    }
    typing.innerHTML = d.busy ? esc(d.status || 'modele pracują') + '<span class="dots"></span>' : '';
    send.disabled = d.busy;
  }catch(err){ /* serwer chwilowo zajęty */ }
  setTimeout(poll, 1200);
}

async function submit(){
  const text = inp.value.trim();
  if(!text) return;
  const r = await fetch('/api/send', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({text})});
  if(r.status === 409){ toast('Modele jeszcze piszą — poczekaj chwilę'); return; }
  if(!r.ok){ toast('Błąd wysyłania'); return; }
  inp.value = '';
}
send.onclick = submit;
inp.addEventListener('keydown', e => { if(e.key === 'Enter') submit(); });
poll();
</script>
</body>
</html>"""

# ──────────────────────────────────────────────────────────────────────────────

def main():
    global OPTS, AGENTS
    ap = argparse.ArgumentParser(description="Pokój w przeglądarce — komunikator Twoich agentów AI.")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--mock", action="store_true", help="symulacja bez prawdziwych CLI")
    ap.add_argument("--agents", default="agents.json", help="plik konfiguracji agentów")
    ap.add_argument("--only", default="", help="ogranicz skład, np. --only claude,codex")
    ap.add_argument("--nick", default="szef", help="Twój podpis (domyślnie: szef)")
    ap.add_argument("--tail", type=int, default=6000, help="ile znaków historii dostają modele")
    ap.add_argument("--timeout", type=int, default=300, help="limit [s] na wypowiedź")
    ap.add_argument("--timeout-exec", type=int, default=3600,
                    help="limit [s] na wykonanie zadania przez zwycięzcę rady")
    ap.add_argument("--no-sprostowania", action="store_true")
    ap.add_argument("--no-open", action="store_true", help="nie otwieraj przeglądarki")
    OPTS = ap.parse_args()

    AGENTS = rada.load_agents(OPTS.agents, OPTS.only)
    if not AGENTS:
        print(rada.red("Brak włączonych agentów — sprawdź agents.json lub flagę --only."))
        sys.exit(1)

    addr = f"http://localhost:{OPTS.port}"
    print(rada.bold("Pokój w przeglądarce: ") + rada.cyan(addr) +
          rada.dim(f"  agenci: {', '.join(AGENTS)}{'  [MOCK]' if OPTS.mock else ''}  (Ctrl+C kończy)"))
    if not OPTS.no_open:
        threading.Timer(0.8, lambda: webbrowser.open(addr)).start()
    try:
        ThreadingHTTPServer(("127.0.0.1", OPTS.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nDo zobaczenia.")

if __name__ == "__main__":
    main()
