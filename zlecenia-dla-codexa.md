# Zlecenia dla Codexa (Build Week: dowód użycia + realne naprawy)

Konkurs wymaga zbudowania projektu **Codexem z GPT‑5.6** (Session ID + opowieść
"where Codex accelerated your workflow" w wideo). Zamiast pozorować — dajemy Codexowi
prawdziwą robotę: cztery średnie znaleziska z code review, które wciąż są otwarte.

## Jak odpalać

W katalogu projektu (repo git!) uruchom interaktywnie `codex` i wklejaj zlecenia
po kolei, albo jednorazowo:

```bash
codex exec --sandbox workspace-write "treść zlecenia…"
```

Po sesji: zanotuj Session ID (`/feedback` w Codexie) i po jednym zdaniu, co zrobił —
to wprost wymagane w zgłoszeniu. Po każdym zleceniu odpal `python3 -m unittest test_rada -v`
i tryb `--mock`, żeby potwierdzić, że nic się nie zepsuło.

---

## Zlecenie 1 — wicemistrz według głosowania (rada.py)

> W pliku rada.py, w funkcji council_run, recenzentem (--review) zostaje agent
> z najwyższą deklarowaną pewnością spośród przegranych — a powinien nim być
> wicemistrz GŁOSOWANIA, czyli drugi wynik punktacji Bordy (przy braku ważnych
> głosów: dopiero wtedy pewność). W web.py w funkcji process_rada jest już
> poprawna wersja tej logiki — przenieś ten sam mechanizm do rada.py.
> Dopisz test do test_rada.py, który to sprawdza.

## Zlecenie 2 — błąd agenta to nie PASS (pokoj.py i web.py)

> W pokoj.py (handle_message, runda wtrąceń) i web.py (process, runda wtrąceń)
> agent, którego wywołanie się nie powiodło (ok=False), jest traktowany tak samo
> jak agent, który odpowiedział PASS. Rozdziel te przypadki: nieudane wywołanie
> ma być raportowane osobno (np. "niedostępny: <błąd>"), a nie liczone jako brak
> uwag. Zachowaj obecne zachowanie dla prawdziwego PASS. Dopisz test.

## Zlecenie 3 — one-shot :debata (pokoj.py)

> W pokoj.py komenda ":debata temat" działa tylko w trybie REPL. Uruchomienie
> jednorazowe `python3 pokoj.py ":debata temat"` trafia do handle_message i robi
> zwykły panel zamiast debaty. Spraw, by ścieżka one-shot rozpoznawała komendy
> zaczynające się od ":" tak samo jak REPL. Dopisz test lub pokaż wynik w --mock.

## Zlecenie 4 — spójny schemat zapisu przy routingu ręcznym (rada.py)

> W rada.py przebieg z ręcznym routingiem ("@agent zadanie") zapisuje w rekordzie
> pola o innej strukturze niż zwykły przebieg: votes to string "pominięte...",
> a result to tekst zamiast słownika z run_agent. Ujednolić: record ma zawsze
> ten sam kształt (votes: dict lub null + pole "routing": "reczny"/"przetarg",
> result: pełny słownik z run_agent). Zaktualizuj save_run/append_memory, jeśli
> trzeba, i dopisz test odczytujący zapisany JSON.

## Zlecenie 5 — przenośność Windows

> W projekcie są problemy przenośności na Windows. Napraw trzy rzeczy:
> 1. W test_rada.py klasa Test1_Returncode używa poleceń ["sh", "-c", ...], których
> nie ma na Windows. Zastąp je przenośnym [sys.executable, "-c", "..."] (print +
> sys.exit(kod)), tak by wszystkie testy przechodziły na Windows, Linuksie i macOS
> bez zmiany tego, co weryfikują.
> 2. rada.py, pokoj.py i web.py wypisują znaki Unicode (✓, ✗, 🗳, —, „"), które
> wywracają konsolę Windows cp1250 (UnicodeEncodeError). Na starcie każdego z trzech
> entry pointów dodaj w try/except:
> sys.stdout.reconfigure(encoding="utf-8", errors="replace") i to samo dla
> sys.stderr. Nie zmieniaj treści komunikatów.
> 3. Dopisz w README krótką sekcję „Windows" (2–3 zdania: UTF-8, ewentualnie
> `chcp 65001`). Na koniec: python3 -m unittest test_rada -v musi być w całości zielone.

---

## Po wszystkim

1. `python3 -m unittest test_rada -v` — komplet zielony.
2. `python3 rada.py --mock --review "test"` i `python3 pokoj.py --mock ":debata test"` — działa.
3. Commit po każdym zleceniu (osobne commity = czytelna historia dla sędziów).
4. Zapisz: Session ID + lista "co zrobił Codex" → wejdzie do opisu i wideo.
