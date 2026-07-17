# Scenariusz demo na Build Week (zadania + wideo 60–90 s)

Cel: 8–12 przebiegów rady na żywych agentach, jeden przypadek „rada wybrała lepiej niż
ręczny wybór", pierwszy ranking i materiał na film. Wszystko robisz u siebie; poniżej
kolejność, komendy i dramaturgia.

## 0. Przygotowanie (15 min)

1. Repo po Zleceniach 1–5 Codexa, testy zielone: `python3 -m unittest test_rada -v`.
2. Zaloguj i sprawdź wszystkie CLI ręcznie: `claude -p "ping"`, `codex exec "ping"`,
   `gemini -p "ping"`, `grok -p "ping"`. Padnięty agent w demo = stracone ujęcie.
3. Świeża pamięć: usuń katalog `rada_memory/` (czysta historia do filmu).
4. Uruchom `python3 web.py` — demo kręcimy w przeglądarce, nie w terminalu.
5. Miej otwarty mały projekt-poligon (repo z gitem), na którym agenci mogą
   bezpiecznie pracować — commit przed każdym zadaniem wykonawczym.

## 1. Dziesięć zadań (dobrane pod różne profile agentów)

Wpisuj w web UI jako `:rada …`, po jednym, czekaj na pełną kartę przebiegu:

1. `:rada Napraw failujący test w tym repo` — teren Claude/Codex.
2. `:rada Zrefaktoryzuj najdłuższą funkcję w projekcie na mniejsze, z zachowaniem zachowania` 
3. `:rada Napisz testy jednostkowe dla modułu X (pokryj przypadki brzegowe)`
4. `:rada Przeczytaj całe repo i wypisz 5 największych długów technicznych` — teren Gemini (kontekst).
5. `:rada Napisz regex walidujący polskie kody pocztowe i numery NIP + testy` — małe zadanie, szansa Groka.
6. `:rada Zaproponuj architekturę cache dla naszego API (bez implementacji)` — zadanie koncepcyjne.
7. `:rada Przeanalizuj plik logów app.log i wskaż anomalie` — podłóż plik z 2-3 ukrytymi błędami.
8. `:rada Napisz sekcję instalacji do README po angielsku` — zadanie pisarskie.
9. `:rada Zoptymalizuj tę funkcję pod kątem złożoności` — algorytmika.
10. `:rada Dodaj obsługę flagi --version do rada.py` — **moment na film: rada ulepsza samą siebie.**

Po każdym: rzut oka na kartę (oferty→głosy→wykonanie→recenzja) i na diff w repo-poligonie.
Zadania 11-12 w zapasie: coś z Twojej realnej pracy — najlepiej wypada autentyk.

## 2. Przypadek „rada > ręczny wybór" (gwóźdź programu)

Potrzebujemy jednego przebiegu, w którym **zwycięzca głosowania ≠ agent z najwyższą
samooceną** — i wynik jest dobry. Jak go znaleźć:

1. Przeglądaj karty z zadań 1–10: szukaj przebiegu, gdzie tablica wyników pokazuje
   zwycięzcę innego niż najwyższa „pewność" na kartach ofert.
2. Kontrpróba na tym samym zadaniu: `python3 rada.py --no-vote "to samo zadanie"` —
   wykona je „pewniak". Porównaj oba wyniki/diffy i werdykty recenzenta.
3. To zdanie mówisz w wideo: *„Ręcznie dałbym to zadanie X, bo brzmiał najpewniej.
   Rada w ślepym głosowaniu wybrała Y — i recenzja pokazuje, że miała rację."*

Jeśli w 10 zadaniach taki rozjazd nie wystąpi — pokaż odwrotność: głosowanie potwierdza
oczywisty wybór, a wartością jest uzasadnienie + recenzja + zapis (też uczciwa narracja).

## 3. Ranking (do filmu i do README)

```bash
python3 ranking.py            # pełne zestawienie
python3 ranking.py --krotko   # sama tabela (na zrzut)
```

Zrzut tabeli → README + jedno ujęcie w wideo. To odpowiedź na pytanie sędziów
„skąd wiadomo, że to działa": starty, wygrane, recenzje, trafność jurorów.

## 4. Storyboard wideo (60–90 s, audio po angielsku — wymóg konkursu)

| Czas | Obraz | Głos (EN, sens) |
|---|---|---|
| 0–10 s | logo/tytuł + jedno zdanie na ekranie | „Models bid anonymously for a task, vote on the best plan, and the runner-up reviews the winner." |
| 10–35 s | web UI: wpisujesz `:rada …` (zadanie 10), pojawiają się karty ofert z paskami | „Four coding agents from four vendors receive the task. Each bids: confidence, plan, risks. No one sees who wrote what." |
| 35–50 s | głosy + tablica z 🏆 | „They vote blind — Borda count picks the executor. Here the most confident agent actually lost the vote." (jeśli masz przypadek z pkt 2) |
| 50–65 s | wykonanie + recenzja ✅ + diff w repo | „The winner executes in my repo; the runner-up reviews the result." |
| 65–80 s | `ranking.py` + `runs/*.json` w edytorze | „Every decision is audited — bids, votes, reviews. Over time it ranks who really delivers." |
| 80–90 s | zakończenie: repo + napis | „Built during Build Week **with Codex on GPT‑5.6** — Codex fixed four review findings itself [pokaż commity]. Rada Modeli: a vendor-neutral control plane for AI coding agents." |

Nagranie: OBS albo nagrywanie ekranu systemowe, 1080p, jasna czcionka przeglądarki
(Ctrl+`+`), kursor powiększony. Audio: prosty angielski wystarczy; **musi paść, jak
użyłeś Codexa i GPT‑5.6** (pokaż commity z zleceń 1–5 i wspomnij Session ID).
Limit konkursu: poniżej 3 minut, YouTube publiczny.

## 5. Checklista przed nagraniem

- [ ] testy zielone po zleceniach Codexa
- [ ] wszystkie 4 CLI odpowiadają na ping
- [ ] świeże `rada_memory/`, czysty poligon z gitem
- [ ] 10 zadań przećwiczone na sucho (wiesz, ile trwają)
- [ ] znaleziony przypadek z pkt 2 (albo plan B)
- [ ] tabela rankingu wygląda sensownie
- [ ] tekst lektorski przeczytany 2× na głos
