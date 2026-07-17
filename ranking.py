#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RANKING — zestawienie skuteczności agentów na podstawie zapisów rady.

Czyta rada_memory/runs/*.json (przebiegi z rada.py i z web.py) i liczy per agent:
  starty, wygrane przetargi, sredni deklarowany confidence, sredni czas oferty,
  wynik recenzji jako wykonawca, trafnosc jurora (1. miejsce w glosie == zwyciezca).

Uzycie:
  python3 ranking.py            # tabela + lista przebiegow
  python3 ranking.py --krotko   # sama tabela
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rada  # noqa: E402

try:  # Windows cp1250: nie wywracaj sie na znakach spoza strony kodowej
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

RUNS = rada.RUNS_DIR


def wczytaj_przebiegi():
    if not RUNS.exists():
        return []
    out = []
    for f in sorted(RUNS.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError, OSError):
            continue
    return out


def analizuj(przebiegi):
    S = {}  # agent -> statystyki

    def st(n):
        return S.setdefault(n, {"starty": 0, "wygrane": 0, "conf_suma": 0, "conf_n": 0,
                                "czas_suma": 0.0, "czas_n": 0, "rec_ok": 0, "rec_all": 0,
                                "juror_traf": 0, "juror_n": 0})

    for r in przebiegi:
        winner = r.get("winner")
        bids = r.get("bids")
        if isinstance(bids, dict):
            for n, res in bids.items():
                if not isinstance(res, dict):
                    continue
                s = st(n)
                s["starty"] += 1
                parsed = rada.extract_json_block(res.get("text") or "")
                if isinstance(parsed, dict) and "confidence" in parsed:
                    try:
                        s["conf_suma"] += int(parsed["confidence"])
                        s["conf_n"] += 1
                    except (TypeError, ValueError):
                        pass
                if isinstance(res.get("seconds"), (int, float)):
                    s["czas_suma"] += res["seconds"]
                    s["czas_n"] += 1
        if winner:
            st(winner)["wygrane"] += 1

        # trafnosc jurora — tylko tam, gdzie zapis ma mape anonimizacji (przebiegi z web)
        mapping = r.get("mapping") or {}
        votes = r.get("votes")
        if winner and mapping and isinstance(votes, dict):
            for n, res in votes.items():
                if not isinstance(res, dict):
                    continue
                pv = rada.extract_json_block(res.get("text") or "")
                ranking = pv.get("ranking") if isinstance(pv, dict) else None
                if isinstance(ranking, list) and ranking:
                    s = st(n)
                    s["juror_n"] += 1
                    first = mapping.get(str(ranking[0]).strip().upper())
                    if first == winner:
                        s["juror_traf"] += 1

        rev = r.get("review")
        if winner and isinstance(rev, dict):
            parsed = rev.get("parsed")
            if isinstance(parsed, dict):
                s = st(winner)
                s["rec_all"] += 1
                if parsed.get("ok"):
                    s["rec_ok"] += 1
    return S


def fmt(v, suf=""):
    return ("-" if v is None else f"{v}{suf}")


def main():
    ap = argparse.ArgumentParser(description="Ranking agentow na podstawie zapisow rady.")
    ap.add_argument("--krotko", action="store_true", help="sama tabela, bez listy przebiegow")
    opts = ap.parse_args()

    przebiegi = wczytaj_przebiegi()
    if not przebiegi:
        print("Brak zapisow w rada_memory/runs/ — najpierw uruchom kilka zadan przez rade.")
        return
    S = analizuj(przebiegi)
    mocki = sum(1 for r in przebiegi if r.get("mock"))

    print(f"\nRANKING AGENTOW  (przebiegow: {len(przebiegi)}, w tym mock: {mocki})")
    print("=" * 78)
    naglowek = f"{'agent':<10}{'starty':>7}{'wygrane':>9}{'win%':>7}{'sr.conf':>9}{'sr.czas':>9}{'recenzje':>10}{'juror':>8}"
    print(naglowek)
    print("-" * 78)
    kolej = sorted(S.items(), key=lambda kv: (-kv[1]["wygrane"], kv[0]))
    for n, s in kolej:
        winp = f"{100 * s['wygrane'] / s['starty']:.0f}%" if s["starty"] else "-"
        conf = f"{s['conf_suma'] / s['conf_n']:.0f}" if s["conf_n"] else "-"
        czas = f"{s['czas_suma'] / s['czas_n']:.1f}s" if s["czas_n"] else "-"
        rec = f"{s['rec_ok']}/{s['rec_all']} OK" if s["rec_all"] else "-"
        jur = f"{s['juror_traf']}/{s['juror_n']}" if s["juror_n"] else "-"
        print(f"{n:<10}{s['starty']:>7}{s['wygrane']:>9}{winp:>7}{conf:>9}{czas:>9}{rec:>10}{jur:>8}")
    print("-" * 78)
    print("sr.conf = srednia deklarowana pewnosc | sr.czas = sredni czas oferty")
    print("recenzje = werdykty recenzenta dla agenta jako WYKONAWCY")
    print("juror = ile razy 1. miejsce w glosie agenta wskazalo ostatecznego zwyciezce")
    print("        (liczone tylko dla przebiegow z zapisana mapa anonimizacji)")

    if not opts.krotko:
        print(f"\nPRZEBIEGI")
        print("-" * 78)
        for r in przebiegi:
            task = rada.short(str(r.get("task", "?")), 46)
            zn = "[M]" if r.get("mock") else "   "
            rev = r.get("review") or {}
            pr = rev.get("parsed") if isinstance(rev, dict) else None
            rtxt = ("rec:OK" if (isinstance(pr, dict) and pr.get("ok"))
                    else ("rec:UWAGI" if isinstance(pr, dict) else ""))
            print(f"{zn} {r.get('run_id','?'):<12} {str(r.get('winner','?')):<9} {rtxt:<10} {task}")
    print()


if __name__ == "__main__":
    main()
