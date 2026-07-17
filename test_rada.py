#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Testy regresyjne dla czterech błędów wykrytych w code review v0.
Każda klasa odpowiada jednemu znalezisku — test najpierw reprodukuje bug,
potem sprawdza, że naprawa działa.

Uruchom:  python3 -m unittest test_rada -v
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import rada
import pokoj
import web


def cichy(func, *args, **kwargs):
    """Uruchom funkcję tłumiąc jej wydruki na stdout (load_agents lubi printować)."""
    with contextlib.redirect_stdout(io.StringIO()):
        return func(*args, **kwargs)


class Test1_Returncode(unittest.TestCase):
    """#1 (Krytyczny): proces z niezerowym kodem wyjścia nie może uchodzić za udany."""

    def test_niezerowy_kod_z_tekstem_to_blad(self):
        cfg = {"bid_cmd": ["sh", "-c", "echo 'BŁĄD wykonania'; exit 7"]}
        r = rada.run_agent("t", cfg, "bid", "x", "x", timeout=10, mock=False, cwd=".")
        self.assertFalse(r["ok"], "proces exit 7 nie może być ok=True")
        self.assertEqual(r["returncode"], 7)

    def test_kod_zero_z_tekstem_jest_ok(self):
        cfg = {"bid_cmd": ["sh", "-c", "echo DZIALA"]}
        r = rada.run_agent("t", cfg, "bid", "x", "x", timeout=10, mock=False, cwd=".")
        self.assertTrue(r["ok"])
        self.assertIn("DZIALA", r["text"])

    def test_kod_zero_ale_pusto_to_blad(self):
        cfg = {"bid_cmd": ["sh", "-c", "exit 0"]}
        r = rada.run_agent("t", cfg, "bid", "x", "x", timeout=10, mock=False, cwd=".")
        self.assertFalse(r["ok"])

    def test_brak_polecenia(self):
        cfg = {"bid_cmd": ["nieistniejace_polecenie_rada_xyz"]}
        r = rada.run_agent("t", cfg, "bid", "x", "x", timeout=10, mock=False, cwd=".")
        self.assertFalse(r["ok"])
        self.assertIn("PATH", r["error"])


class Test2_LoadAgents(unittest.TestCase):
    """#2 (Krytyczny): sekcje metadanych (_rules, _uwaga) nie mogą wywracać ładowania."""

    def _zapisz(self, obj):
        fd, sciezka = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        Path(sciezka).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        self.addCleanup(os.unlink, sciezka)
        return sciezka

    def test_rozszerzony_z_rules_laduje_sie(self):
        cfg = {
            "_uwaga": "komentarz",
            "_rules": [{"gdy": ["x"], "wykonawca": "claude"}],
            "grok": {"enabled": True, "bid_cmd": ["grok", "-p", "{prompt}"]},
        }
        agents = cichy(rada.load_agents, self._zapisz(cfg), "")
        self.assertNotIn("_uwaga", agents)
        self.assertNotIn("_rules", agents)
        self.assertIn("grok", agents)  # prawdziwy agent nadal się ładuje

    def test_agent_nie_bedacy_obiektem_jest_pomijany(self):
        cfg = {"zły": "to nie jest obiekt", "claude": {"enabled": True}}
        agents = cichy(rada.load_agents, self._zapisz(cfg), "")
        self.assertNotIn("zły", agents)
        self.assertIn("claude", agents)

    def test_prawdziwy_plik_rozszerzony(self):
        # jeśli agents.rozszerzony.json leży obok — musi się ładować bez wyjątku
        if Path("agents.rozszerzony.json").exists():
            agents = cichy(rada.load_agents, "agents.rozszerzony.json", "")
            self.assertIn("claude", agents)


class Test3_Borda(unittest.TestCase):
    """#3 (Wysoki): głosowanie Bordy musi ignorować duplikaty w rankingu jurora."""

    def test_duplikaty_nie_kumuluja_punktow(self):
        pts = rada.tally_votes(["A", "B", "C", "D"], {"j": ["A", "A", "A", "A"]})
        self.assertLessEqual(pts["A"], 3, "A>A>A>A nie może dać więcej niż za 1. miejsce")
        self.assertEqual(pts["A"], 3)

    def test_normalne_glosowanie(self):
        # dwóch jurorów, ranking pełny
        pts = rada.tally_votes(["A", "B", "C"],
                               {"j1": ["A", "B", "C"], "j2": ["B", "A", "C"]})
        # A: 2+1=3, B: 1+2=3, C: 0+0=0
        self.assertEqual(pts["A"], 3)
        self.assertEqual(pts["B"], 3)
        self.assertEqual(pts["C"], 0)

    def test_czesciowy_ranking(self):
        pts = rada.tally_votes(["A", "B", "C"], {"j": ["A"]})  # juror wskazał tylko A
        self.assertEqual(pts["A"], 2)
        self.assertEqual(pts["B"], 0)

    def test_nieznane_id_ignorowane(self):
        pts = rada.tally_votes(["A", "B"], {"j": ["A", "Z", "B"]})  # Z nie istnieje
        self.assertEqual(pts["A"], 1)
        self.assertEqual(pts["B"], 0)


class Test4_JsonParser(unittest.TestCase):
    """#4 (Wysoki): parser obiektu JSON musi ignorować klamry wewnątrz stringów."""

    def test_zamykajaca_klamra_w_stringu(self):
        txt = '{"confidence": 80, "approach": "użyj słownika }", "risks": "brak"}'
        parsed = rada.extract_json_block(txt)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["confidence"], 80)

    def test_otwierajaca_klamra_w_stringu(self):
        txt = '{"approach": "kod: def f() { return 1", "confidence": 50}'
        parsed = rada.extract_json_block(txt)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["confidence"], 50)

    def test_escapowany_cudzyslow(self):
        txt = r'{"approach": "on rzekł \"gotowe}\" i wyszedł", "confidence": 42}'
        parsed = rada.extract_json_block(txt)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["confidence"], 42)

    def test_json_otoczony_tekstem(self):
        txt = 'Oto moja oferta:\n{"confidence": 90}\nMam nadzieję, że pomoże.'
        parsed = rada.extract_json_block(txt)
        self.assertEqual(parsed["confidence"], 90)

    def test_zagniezdzony_obiekt(self):
        txt = '{"a": {"b": 1}, "confidence": 7}'
        parsed = rada.extract_json_block(txt)
        self.assertEqual(parsed["a"]["b"], 1)
        self.assertEqual(parsed["confidence"], 7)

    def test_brak_jsona(self):
        self.assertIsNone(rada.extract_json_block("brak tu żadnego obiektu"))


class Test5_ReviewerBorda(unittest.TestCase):
    """Recenzentem ma być wicemistrz głosowania, nie samooceny pewności."""

    def test_recenzent_jest_wicemistrzem_glosowania(self):
        agents = {n: {"opis": ""} for n in ("alpha", "beta", "gamma")}

        def wynik(text):
            return {"ok": True, "text": text, "stderr": "", "seconds": 0,
                    "error": None, "returncode": 0}

        bids = {
            "alpha": wynik('{"confidence": 100, "approach": "A"}'),
            "beta": wynik('{"confidence": 10, "approach": "B"}'),
            "gamma": wynik('{"confidence": 20, "approach": "C"}'),
        }
        votes = {n: wynik('{"ranking": ["C", "B", "A"]}') for n in agents}

        def run_parallel(_agents, phase, _prompts, _task, _timeout, _mock, _cwd):
            return bids if phase == "bid" else votes

        def run_agent(_name, _cfg, phase, _prompt, _task, _timeout, _mock, _cwd):
            if phase == "review":
                return wynik('{"ok": true, "uwagi": "dobrze"}')
            return wynik("wykonane")

        saved = []
        opts = SimpleNamespace(mock=True, no_vote=False, review=True,
                               timeout_bid=1, timeout_exec=1, cwd=".")
        order = {"alpha": 0, "beta": 1, "gamma": 2}

        with mock.patch.object(rada, "read_memory", return_value=""), \
                mock.patch.object(rada, "stable_hash", side_effect=lambda text: next(
                    value for name, value in order.items() if text.endswith(name))), \
                mock.patch.object(rada, "run_parallel", side_effect=run_parallel), \
                mock.patch.object(rada, "run_agent", side_effect=run_agent), \
                mock.patch.object(rada, "save_run",
                                  side_effect=lambda _run_id, record: saved.append(record)), \
                mock.patch.object(rada, "append_memory"):
            cichy(rada.council_run, "zadanie", agents, opts)

        self.assertEqual(saved[0]["winner"], "gamma")
        self.assertEqual(saved[0]["review"]["reviewer"], "beta")


class Test6_InterjectionErrors(unittest.TestCase):
    """Błąd agenta w rundzie sprostowań nie może uchodzić za PASS."""

    def setUp(self):
        self.agents = {n: {} for n in ("target", "offline", "passer")}
        self.opts = SimpleNamespace(nick="szef", tail=1000, no_sprostowania=False,
                                    mock=False, timeout=1)
        self.answer = {"ok": True, "text": "odpowiedź", "error": None}
        self.interjections = {
            "offline": {"ok": False, "text": "", "error": "timeout"},
            "passer": {"ok": True, "text": "PASS", "error": None},
        }

    def test_pokoj_raportuje_blad_zamiast_wszyscy_pass(self):
        output = io.StringIO()
        with mock.patch.object(pokoj, "append_msg"), \
                mock.patch.object(pokoj, "transcript_tail", return_value=""), \
                mock.patch.object(pokoj, "say", return_value=self.answer), \
                mock.patch.object(pokoj, "say_parallel", return_value=self.interjections), \
                mock.patch.object(pokoj, "speak"), \
                contextlib.redirect_stdout(output):
            pokoj.handle_message("@target pytanie", self.agents, self.opts)

        self.assertIn("offline niedostępny: timeout", output.getvalue())
        self.assertNotIn("wszyscy: PASS", output.getvalue())

    def test_web_oddziela_blad_od_prawdziwego_pass(self):
        messages = []

        def append_msg(frm, to, typ, content):
            messages.append((frm, to, typ, content))

        with mock.patch.object(web, "AGENTS", self.agents), \
                mock.patch.object(web, "OPTS", self.opts), \
                mock.patch.object(pokoj, "append_msg", side_effect=append_msg), \
                mock.patch.object(pokoj, "transcript_tail", return_value=""), \
                mock.patch.object(pokoj, "say", return_value=self.answer), \
                mock.patch.object(pokoj, "say_parallel", return_value=self.interjections), \
                mock.patch.object(web, "set_status"):
            web.process("@target pytanie")

        contents = [content for _frm, _to, _typ, content in messages]
        self.assertIn("offline niedostępny: timeout", contents)
        self.assertIn("bez uwag (PASS): passer", contents)


class Test7_OneShotDebate(unittest.TestCase):
    """Komenda :debata ma działać również poza trybem REPL."""

    def test_main_kieruje_one_shot_do_debaty(self):
        agents = {"claude": {}}
        with mock.patch.object(sys, "argv", ["pokoj.py", "--mock", ":debata", "test"]), \
                mock.patch.object(rada, "load_agents", return_value=agents), \
                mock.patch.object(pokoj, "debate") as debate_mock, \
                mock.patch.object(pokoj, "handle_message") as message_mock:
            pokoj.main()

        debate_mock.assert_called_once()
        self.assertEqual(debate_mock.call_args.args[:2], ("test", agents))
        message_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
