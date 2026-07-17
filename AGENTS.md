# AGENTS.md — instrukcje dla agenta pracującego w tym repo

## Czym jest ten projekt

**Rada Modeli** — lokalny orkiestrator agentów AI (Claude Code, Codex, Gemini CLI,
Grok Build): agenci składają oferty na zadanie, głosują anonimowo (Borda), zwycięzca
wykonuje, wicemistrz recenzuje. Stan: działające v0.1 po zewnętrznym code review.
Trwa sprint na OpenAI Build Week (deadline 21.07) — pracujemy małymi, pewnymi krokami.

## Twoja rola

Wykonuj wyłącznie zadania opisane w `zlecenia-dla-codexa.md`, po kolei, **jedno
zlecenie = jeden commit** z czytelnym opisem. Nie podejmuj się niczego spoza zleceń
bez wyraźnej prośby użytkownika.

## Architektura (nie zmieniaj jej)

- `rada.py` — rdzeń: przetarg (oferty → anonimowe głosowanie → wykonanie → recenzja),
  pamięć w `rada_memory/` (journal.md + runs/*.json), tryb `--mock` (symulacja bez CLI).
- `pokoj.py` — czat grupowy modeli ze sprostowaniami; importuje `rada`.
- `web.py` — komunikator w przeglądarce (serwer HTTP ze stdlib); importuje `rada` i `pokoj`.
  Funkcja `process_rada` zawiera WZORCOWĄ logikę wyboru recenzenta wg Bordy (Zlecenie 1
  polega na przeniesieniu jej do `rada.py`).
- `test_rada.py` — 17 testów regresyjnych po code review. Wszystkie muszą przechodzić.

## Twarde zasady (antydrift)

1. **Wyłącznie biblioteka standardowa Pythona.** Zero nowych zależności, zero pip.
2. **Nie przebudowuj architektury.** Bez asyncio, SQLite, streamingu, ACP, refaktoru
   struktury plików — to świadomie odłożone na po konkursie.
3. Polecenia agentów zawsze jako **tablice argumentów** (`subprocess` bez shella).
4. Komentarze, komunikaty i nazwy w stylu istniejącym (po polsku).
5. Nie zmieniaj wyglądu ani struktury HTML/CSS w `web.py` (stała `PAGE`), chyba że
   zlecenie tego wymaga.
6. **Nie modyfikuj istniejących testów** — tylko dopisuj nowe. Nie cofaj napraw
   z v0.1: kontrola `returncode`, pomijanie `_rules`/`_uwaga` w konfiguracji,
   deduplikacja rankingu Bordy, parser JSON odporny na klamry w stringach.
7. Tryb `--mock` musi działać po każdej zmianie (to podstawa testów i demo).

## Jak weryfikować pracę (definicja "zrobione")

```bash
python3 -m unittest test_rada -v          # komplet zielony
python3 rada.py --mock --review "test"    # pełny przebieg przetargu
python3 pokoj.py --mock ":debata test"    # po Zleceniu 3: debata, nie panel
python3 web.py --mock --no-open           # smoke: serwer wstaje bez wyjątków
```

Zlecenie jest zakończone, gdy: testy przechodzą, mock działa, commit zrobiony,
a w odpowiedzi podajesz krótkie podsumowanie zmian (pliki + co i dlaczego).
