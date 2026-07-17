# Rada Modeli 🗳️

Jeden hub, w którym Twoje agenty AI — **Claude Code, Codex, Gemini CLI i Grok Build** — wspólnie
decydują, kto najlepiej wykona zadanie. Zamiast przełączać się między aplikacjami, piszesz jedno
polecenie, a modele same rozstrzygają między sobą (wzorzec *Contract Net* — przetarg ofert).

## Jak to działa

```
        Twoje zadanie
             │
   ┌─────────┼─────────┬─────────┐
   ▼         ▼         ▼         ▼
 claude    codex     gemini    grok      [1/3] PRZETARG — każdy składa ofertę:
   │         │         │         │              pewność 0-100, plan, ryzyka, nakład
   └────┬────┴────┬────┴────┬────┘
        ▼         ▼         ▼
     GŁOSOWANIE (oferty ANONIMOWE)       [2/3] RADA — każdy agent ocenia oferty,
        │                                       nie wiedząc, która jest jego
        ▼
     ZWYCIĘZCA wykonuje zadanie          [3/3] WYKONANIE w Twoim projekcie
        │
        ▼
     wspólna pamięć (journal.md)         + opcjonalna recenzja wicemistrza (--review)
```

Anonimizacja ofert to celowy zabieg: modele pytane wprost "czy dasz radę?" niemal zawsze
odpowiadają "tak". Gdy oceniają cudze plany w ciemno, robią to o wiele trzeźwiej.
Głosy liczone są metodą Bordy (1. miejsce = najwięcej punktów), remis rozstrzyga
deklarowana pewność.

## Wymagania

- Python 3.9+ (sam standard library, zero zależności)
- Zainstalowane i **zalogowane** CLI agentów, których chcesz używać:
  - `claude` — Claude Code
  - `codex` — Codex CLI
  - `gemini` — Gemini CLI
  - `grok` — Grok Build CLI

Brakujące CLI nie psują zabawy — hub je wykrywa i po prostu pomija ("brak polecenia w PATH").

### Windows

Program przełącza standardowe wyjście i strumień błędów na UTF-8, aby znaki interfejsu
działały również w konsoli Windows. W starszym terminalu można dodatkowo wykonać
`chcp 65001` przed uruchomieniem programu.

## Szybki start

```bash
# 1. Test przepływu bez żadnych CLI (symulacja):
python3 rada.py --mock "Zrefaktoryzuj moduł płatności i dodaj testy"

# 2. Na serio, w katalogu Twojego projektu:
cd ~/moj-projekt
python3 /sciezka/do/rada.py "Dodaj tryb ciemny do aplikacji"

# 3. Tryb rozmowy (kolejne zadania jedno po drugim):
python3 rada.py
```

## Użycie

```
python3 rada.py [zadanie] [flagi]

  "@codex zadanie"       ręczne ominięcie rady — zadanie idzie prosto do wskazanego agenta
  --mock                 symulacja (test przepływu bez CLI i bez kosztów)
  --review               po wykonaniu wicemistrz recenzuje wynik zwycięzcy
  --no-vote              pomiń głosowanie; wygrywa najwyższa deklarowana pewność
  --only claude,codex    ogranicz skład rady
  --cwd /sciezka         katalog roboczy dla agentów (Twój projekt)
  --timeout-bid 300      limit [s] na ofertę/głos
  --timeout-exec 3600    limit [s] na wykonanie zadania
  --init                 wygeneruj agents.json do edycji
```

W trybie rozmowy działają komendy `:agenci`, `:pamiec` oraz `exit`.

## Konfiguracja (agents.json)

`python3 rada.py --init` tworzy plik z domyślnymi poleceniami. Możesz w nim:

- wyłączyć agenta: `"enabled": false`
- zmienić model, np. dla Groka: `["grok", "-p", "{prompt}", "-m", "nazwa-modelu", ...]`
- dodać własnego agenta — wystarczy dowolne CLI, które przyjmuje prompt i wypisuje odpowiedź
  (np. lokalny model przez `ollama run ...`); `{prompt}` zostanie podmienione na treść zapytania.

`bid_cmd` służy do ofert/głosów (tanio, bez zmian w plikach), `exec_cmd` do właściwego
wykonania — dlatego tylko tam są flagi auto-zatwierdzania (`--yolo`, `--always-approve`,
`--sandbox workspace-write`, `--permission-mode acceptEdits`).

## Koszty i bezpieczeństwo

- Narzut rady to ~2 krótkie zapytania na agenta (oferta + głos) — kilka(naście) sekund
  i grosze względem samego wykonania zadania. Pełny zapis każdego przebiegu ląduje
  w `rada_memory/runs/*.json`, więc widzisz, kto co powiedział.
- `exec_cmd` pozwala agentom **modyfikować pliki** w `--cwd`. Uruchamiaj w repozytorium
  pod gitem i przeglądaj diffy. Jeśli chcesz pełnej autonomii Claude'a
  (też polecenia bash), zmień w konfiguracji `--permission-mode acceptEdits` na
  `--dangerously-skip-permissions` — świadomie i na własną odpowiedzialność.

## Wspólna pamięć

Każde zadanie dopisuje wpis do `rada_memory/journal.md` (kto wygrał, jak głosowano, skrót
wyniku). Końcówka dziennika jest doklejana do promptów kolejnych zadań, więc agenci znają
wcześniejsze ustalenia — niezależnie od tego, który z nich pracował ostatnio.

## Pokój — czat grupowy modeli (pokoj.py)

Drugi tryb pracy: zamiast przetargu o zadanie — **wspólny wątek rozmowy**, w którym siedzą
wszystkie modele. Każda wiadomość ma podpis "kto → do kogo", wszyscy widzą wszystko,
a po odpowiedzi adresata pozostali mogą wtrącić **sprostowanie**.

```bash
python3 pokoj.py --mock            # symulacja
python3 pokoj.py                   # tryb rozmowy

szef> @grok jaką bazę danych wybrać do aplikacji czatowej?
grok:  ...odpowiada...
… pozostali czytają odpowiedź i mogą się wtrącić …
⚠ sprostowanie od claude: ...
```

- `@grok pytanie` — odpowiada adresat, reszta robi kontrolę jakości (sprostowanie albo PASS)
- pytanie bez `@` — każdy odpowiada krótko (panel opinii)
- `:debata temat` — runda dyskusji: modele zabierają głos po kolei i widzą przedmówców
- aliasy nazw: `chatgpt`/`gpt` → codex, `grog` → grok, `google` → gemini
- zapis rozmowy: `rada_memory/pokoj.md` (czytelny) + `pokoj.jsonl` (strukturalny)

Reguły przeciw kakofonii: wtrącenie maks. 1× na wiadomość, domyślnie PASS, nikt nie
odpowiada na sprostowania automatycznie (kolejny ruch należy do Ciebie), a modele dostają
tylko końcówkę historii (`--tail`, domyślnie 6000 znaków). Rozmowa używa tanich poleceń
`bid_cmd` (bez uprawnień do zmian w plikach) — do wykonywania zadań służy `rada.py`.

## Komunikator w przeglądarce (web.py)

Ten sam pokój, ale jako czat w przeglądarce — dymki, awatary modeli, podpisy
"kto → do kogo", sprostowania oznaczone na żółto i wskaźnik "pisze…".

```bash
python3 web.py --mock        # obejrzyj interfejs bez CLI
python3 web.py               # na żywych agentach (otwiera http://localhost:8787)
```

- działa lokalnie, zero zależności (sam Python) — serwer nasłuchuje tylko na 127.0.0.1
- **`:rada zadanie` — pełny przetarg w przeglądarce**: karty ofert z paskami pewności,
  głosy jurorów, tablica wyników z 🏆, wykonanie przez zwycięzcę i recenzja wicemistrza
  (liczonego z punktacji Bordy); pełny zapis przebiegu w `rada_memory/runs/*.json`
- wszystko z klawiatury albo przez podpowiedzi-chipy: `:rada …`, `@grok …`, `:debata …`
- zapis rozmowy współdzielony z `pokoj.py` (`rada_memory/pokoj.jsonl`),
  więc możesz płynnie przechodzić między terminalem a przeglądarką
- flagi jak w pokoju: `--only`, `--nick`, `--tail`, `--timeout`, `--no-sprostowania`,
  plus `--port` i `--no-open`

## Testy

```bash
python3 -m unittest test_rada -v      # 22 testy regresyjne
```

`test_rada.py` pilnuje czterech błędów wykrytych w code review v0 (każdy test najpierw
reprodukuje buga, potem potwierdza naprawę):

- **returncode** — proces z niezerowym kodem wyjścia nie uchodzi już za udany, nawet
  jeśli coś wypisał na stdout;
- **ładowanie configu** — sekcje metadanych (`_rules`, `_uwaga`) i błędne wpisy są
  pomijane zamiast wywracać program `TypeError`-em;
- **głosowanie Bordy** — duplikaty w rankingu jurora (`A > A > A > A`) nie kumulują
  już punktów;
- **parser JSON** — klamry `{` `}` wewnątrz wartości stringowych nie psują wykrywania
  obiektu.

## Co naprawiono (v0.1, utwardzenie rdzenia)

Pierwsza runda po zewnętrznym code review. Naprawione cztery błędy krytyczne/wysokie
powyżej + dołączone testy. Świadomie **jeszcze nie** ruszane (zgodnie z zaleceniem:
najpierw kontrakty, potem funkcje): streaming, liczenie kosztów, SQLite zamiast JSONL,
prompt-injection w pamięci, ACP, konsensus. Lista otwartych spraw — w
`brief-...md` (sekcja 5) i w werdyktach recenzji.

## Pomysły na rozwój (roadmapa)

1. **Konsensus zamiast zwycięzcy** — kilku agentów wykonuje równolegle, moderator scala najlepsze fragmenty.
2. **Streaming** — podgląd pracy wykonawcy na żywo (`--output-format streaming-json`).
3. **Licznik tokenów/kosztów** — CLI zwracają statystyki użycia w JSON, można je sumować per run.
4. **ACP (Agent Client Protocol)** — zamiast subprocess, trwałe sesje po JSON-RPC (`grok agent stdio` już to wspiera).
5. **Web UI / aplikacja** — dashboard z historią głosowań i diffami zamiast terminala.
