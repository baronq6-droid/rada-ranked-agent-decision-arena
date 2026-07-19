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
        cfg = {"bid_cmd": [sys.executable, "-c",
                           "import sys; print('BŁĄD wykonania'); sys.exit(7)"]}
        r = rada.run_agent("t", cfg, "bid", "x", "x", timeout=10, mock=False, cwd=".")
        self.assertFalse(r["ok"], "proces exit 7 nie może być ok=True")
        self.assertEqual(r["returncode"], 7)

    def test_kod_zero_z_tekstem_jest_ok(self):
        cfg = {"bid_cmd": [sys.executable, "-c", "print('DZIALA')"]}
        r = rada.run_agent("t", cfg, "bid", "x", "x", timeout=10, mock=False, cwd=".")
        self.assertTrue(r["ok"])
        self.assertIn("DZIALA", r["text"])

    def test_kod_zero_ale_pusto_to_blad(self):
        cfg = {"bid_cmd": [sys.executable, "-c", "pass"]}
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


class Test8_ManualRoutingRecord(unittest.TestCase):
    """Routing ręczny ma zapisywać ten sam schemat rekordu co przetarg."""

    def test_zapis_json_ma_routing_i_pelny_wynik(self):
        opts = SimpleNamespace(mock=True, timeout_exec=1, cwd=".")
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp) / "rada_memory"
            runs_dir = memory_dir / "runs"
            journal = memory_dir / "journal.md"
            with mock.patch.object(rada, "MEMORY_DIR", memory_dir), \
                    mock.patch.object(rada, "RUNS_DIR", runs_dir), \
                    mock.patch.object(rada, "JOURNAL", journal):
                cichy(rada.council_run, "@codex zrób test", {"codex": {}}, opts)

            files = list(runs_dir.glob("*.json"))
            self.assertEqual(len(files), 1)
            record = json.loads(files[0].read_text(encoding="utf-8"))

        self.assertEqual(record["routing"], "reczny")
        self.assertIsNone(record["votes"])
        self.assertEqual(record["tally"], "routing ręczny")
        self.assertIsInstance(record["result"], dict)
        self.assertTrue(record["result"]["ok"])
        self.assertIn("text", record["result"])
        self.assertIn("error", record["result"])


class Test9_AgentFailureIsolation(unittest.TestCase):
    """P0: wadliwa konfiguracja jednego agenta nie może wywracać całej rady."""

    RESULT_KEYS = {"ok", "text", "stderr", "seconds", "error", "returncode"}

    def _zapisz(self, obj):
        fd, sciezka = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        Path(sciezka).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        self.addCleanup(os.unlink, sciezka)
        return sciezka

    def test_agent_bez_bid_cmd_zwraca_rekord_bledu(self):
        wynik = rada.run_agent("x", {"enabled": True}, "bid", "p", "t", 5, False, ".")

        self.assertEqual(set(wynik), self.RESULT_KEYS)
        self.assertFalse(wynik["ok"])
        self.assertIsNone(wynik["returncode"])
        self.assertIn("bid_cmd", wynik["error"])

    def test_bid_cmd_jako_string_jest_pomijany_przy_load(self):
        cfg = {
            "wadliwy": {"enabled": True, "bid_cmd": "agent -p", "exec_cmd": ["agent"]},
        }

        agents = cichy(rada.load_agents, self._zapisz(cfg), "")

        self.assertNotIn("wadliwy", agents)

    def test_element_nietekstowy_w_poleceniu_jest_pomijany_przy_load(self):
        cfg = {
            "wadliwy": {"enabled": True, "bid_cmd": ["agent", 7], "exec_cmd": ["agent"]},
        }

        agents = cichy(rada.load_agents, self._zapisz(cfg), "")

        self.assertNotIn("wadliwy", agents)

    def test_wyjatek_jednego_future_nie_gubi_dobrego_wyniku(self):
        dobry = {"ok": True, "text": "ok", "stderr": "", "seconds": 0.0,
                 "error": None, "returncode": 0}

        def worker(name, *_args, **_kwargs):
            if name == "zly":
                raise RuntimeError("awaria workera")
            return dobry

        with mock.patch.object(rada, "run_agent", side_effect=worker):
            wyniki = rada.run_parallel(
                {"dobry": {}, "zly": {}}, "bid", {"dobry": "p", "zly": "p"},
                "t", 5, False, ".")

        self.assertTrue(wyniki["dobry"]["ok"])
        self.assertEqual(set(wyniki["zly"]), self.RESULT_KEYS)
        self.assertFalse(wyniki["zly"]["ok"])
        self.assertIn("RuntimeError", wyniki["zly"]["error"])

    def test_zly_cwd_raportuje_katalog_roboczy(self):
        cwd = str(Path(tempfile.gettempdir()) / f"rada-brak-{os.getpid()}")
        cfg = {"bid_cmd": [sys.executable, "-c", "print('ok')"]}

        wynik = rada.run_agent("x", cfg, "bid", "p", "t", 5, False, cwd)

        self.assertFalse(wynik["ok"])
        self.assertIn("katalog roboczy", wynik["error"].lower())
        self.assertNotIn("PATH", wynik["error"])
        self.assertIsNone(wynik["returncode"])

    def test_pusta_lista_polecenia_ma_czytelny_blad(self):
        wynik = rada.run_agent("x", {"bid_cmd": []}, "bid", "p", "t", 5, False, ".")

        self.assertFalse(wynik["ok"])
        self.assertIn("niepustą listą tekstów", wynik["error"])
        self.assertIsNone(wynik["returncode"])


class Test10_WindowsCliInterop(unittest.TestCase):
    """Wyjście CLI ma być UTF-8, a wielowierszowy prompt może iść przez stdin."""

    def test_wyjscie_utf8_nie_jest_dekodowane_przez_cp1250(self):
        tekst = "Zażółć gęślą jaźń — 😀"
        kod = (
            "import sys; "
            f"sys.stdout.buffer.write({tekst!r}.encode('utf-8'))"
        )

        wynik = rada.run_agent(
            "x", {"bid_cmd": [sys.executable, "-c", kod]},
            "bid", "p", "t", 10, False, ".")

        self.assertTrue(wynik["ok"])
        self.assertEqual(wynik["text"], tekst)

    def test_prompt_stdin_nie_trafia_do_argv(self):
        completed = SimpleNamespace(returncode=0, stdout="ok", stderr="")
        prompt = "pierwsza linia\ndruga linia"
        cfg = {"bid_cmd": ["agent.cmd", "exec", "{prompt_stdin}"]}

        with mock.patch.object(rada.subprocess, "run", return_value=completed) as run_mock:
            wynik = rada.run_agent("x", cfg, "bid", prompt, "t", 10, False, ".")

        args, kwargs = run_mock.call_args
        self.assertTrue(wynik["ok"])
        self.assertEqual(args[0], ["agent.cmd", "exec", "-"])
        self.assertEqual(kwargs["input"], prompt)
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertEqual(kwargs["errors"], "replace")

    def test_prompt_stdin_raw_jest_usuwany_z_argv(self):
        completed = SimpleNamespace(returncode=0, stdout="ok", stderr="")
        prompt = "pierwsza linia\ndruga linia"
        cfg = {
            "bid_cmd": [
                "agent.cmd", "-p", "", "--output-format", "json",
                "{prompt_stdin_raw}",
            ]
        }

        with mock.patch.object(rada.subprocess, "run", return_value=completed) as run_mock:
            wynik = rada.run_agent("x", cfg, "bid", prompt, "t", 10, False, ".")

        args, kwargs = run_mock.call_args
        self.assertTrue(wynik["ok"])
        self.assertEqual(
            args[0], ["agent.cmd", "-p", "", "--output-format", "json"])
        self.assertEqual(kwargs["input"], prompt)


class Test11_DeterministicVerifier(unittest.TestCase):
    """Verifier ma rozstrzygać wynik bez modelu, shella i wycieku sekretów."""

    RESULT_KEYS = {"status", "reason", "stdout", "stderr", "seconds", "returncode"}

    def _zapisz(self, obj):
        fd, sciezka = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        Path(sciezka).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        self.addCleanup(os.unlink, sciezka)
        return sciezka

    def test_brak_konfiguracji_to_inconclusive(self):
        wynik = rada.run_verifier(None, 10, ".")

        self.assertEqual(set(wynik), self.RESULT_KEYS)
        self.assertEqual(wynik["status"], "INCONCLUSIVE")
        self.assertEqual(wynik["reason"], "no verifier configured")
        self.assertIsNone(wynik["returncode"])

    def test_exit_zero_to_pass(self):
        wynik = rada.run_verifier(
            [sys.executable, "-c", "print('verified')"], 10, ".")

        self.assertEqual(wynik["status"], "PASS")
        self.assertEqual(wynik["returncode"], 0)
        self.assertIn("verified", wynik["stdout"])

    def test_exit_niezerowy_to_fail(self):
        wynik = rada.run_verifier(
            [sys.executable, "-c", "import sys; print('fail', file=sys.stderr); sys.exit(9)"],
            10, ".")

        self.assertEqual(wynik["status"], "FAIL")
        self.assertEqual(wynik["returncode"], 9)
        self.assertIn("fail", wynik["stderr"])

    def test_timeout_to_inconclusive(self):
        wynik = rada.run_verifier(
            [sys.executable, "-c", "import time; time.sleep(2)"], 0.05, ".")

        self.assertEqual(wynik["status"], "INCONCLUSIVE")
        self.assertIsNone(wynik["returncode"])

    def test_wyjscie_jest_przyciete_a_sekret_env_niedostepny(self):
        sekret = "sekret-rada-ktory-nie-moze-trafic-do-rekordu"
        kod = (
            "import os,sys; "
            "sys.stdout.write('x'*5000 + os.environ.get('OPENAI_API_KEY', '')); "
            "sys.stderr.write('y'*5000)"
        )
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": sekret}):
            wynik = rada.run_verifier([sys.executable, "-c", kod], 10, ".")

        self.assertEqual(wynik["status"], "PASS")
        self.assertLessEqual(len(wynik["stdout"]), rada.VERIFIER_OUTPUT_LIMIT)
        self.assertLessEqual(len(wynik["stderr"]), rada.VERIFIER_OUTPUT_LIMIT)
        self.assertNotIn(sekret, json.dumps(wynik, ensure_ascii=False))
        self.assertNotIn("env", wynik)

    def test_subprocess_dostaje_argv_i_shell_false(self):
        completed = SimpleNamespace(returncode=0, stdout="ok", stderr="")
        with mock.patch.object(rada.subprocess, "run", return_value=completed) as run_mock:
            rada.run_verifier(["verifier", "--check"], 10, ".")

        args, kwargs = run_mock.call_args
        self.assertEqual(args[0], ["verifier", "--check"])
        self.assertIs(kwargs["shell"], False)
        self.assertIsInstance(kwargs["env"], dict)

    def test_ustawienia_projektu_nie_staja_sie_agentami(self):
        sciezka = self._zapisz({
            "verify_cmd": [sys.executable, "-c", "print('ok')"],
            "verify_timeout": 17,
        })

        command, timeout = rada.load_verifier_settings(sciezka)
        agents = cichy(rada.load_agents, sciezka, "")

        self.assertEqual(command[0], sys.executable)
        self.assertEqual(timeout, 17)
        self.assertNotIn("verify_cmd", agents)
        self.assertNotIn("verify_timeout", agents)

    def test_recenzja_modelowa_nie_nadpisuje_final_status(self):
        record = {"review": {"parsed": {"ok": False, "uwagi": "nie zgadzam się"}}}
        opts = SimpleNamespace(
            verify_cmd=[sys.executable, "-c", "print('ok')"],
            verify_timeout=10,
            cwd=".",
        )

        rada.attach_verifier(record, opts)

        self.assertEqual(record["verifier"]["status"], "PASS")
        self.assertEqual(record["final_status"], "success")
        self.assertFalse(record["review"]["parsed"]["ok"])

    def test_nieudane_wykonanie_nie_moze_dac_final_status_success(self):
        bid = {"ok": True, "text": '{"confidence": 80, "approach": "plan"}',
               "stderr": "", "seconds": 0.0, "error": None, "returncode": 0}
        failed_exec = {"ok": False, "text": "", "stderr": "awaria", "seconds": 0.0,
                       "error": "proces zakończył się kodem 7", "returncode": 7}
        opts = SimpleNamespace(
            mock=False, no_vote=False, review=False, timeout_bid=1, timeout_exec=1,
            cwd=".", verify_cmd=[sys.executable, "-c", "print('ok')"], verify_timeout=10,
        )
        saved = []

        with mock.patch.object(rada, "read_memory", return_value=""), \
                mock.patch.object(rada, "run_parallel", return_value={"alpha": bid}), \
                mock.patch.object(rada, "run_agent", return_value=failed_exec), \
                mock.patch.object(rada, "save_run",
                                  side_effect=lambda _run_id, record: saved.append(record)), \
                mock.patch.object(rada, "append_memory"):
            cichy(rada.council_run, "zadanie", {"alpha": {"opis": ""}}, opts)

        self.assertEqual(saved[0]["verifier"]["status"], "INCONCLUSIVE")
        self.assertEqual(saved[0]["verifier"]["reason"], "execution did not run")
        self.assertEqual(saved[0]["final_status"], "unverified")


class Test12_VoteAuditTrail(unittest.TestCase):
    """Audyt głosowania: zapis runu ma zawierać mapę anonimizacji i punkty Bordy,
    tak by zwycięzcę dało się niezależnie przeliczyć z samego pliku JSON."""

    def _uruchom_rade(self):
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

        saved = []
        opts = SimpleNamespace(mock=True, no_vote=False, review=False,
                               timeout_bid=1, timeout_exec=1, cwd=".",
                               verify_cmd=None, verify_timeout=10)
        order = {"alpha": 0, "beta": 1, "gamma": 2}

        with mock.patch.object(rada, "read_memory", return_value=""), \
                mock.patch.object(rada, "stable_hash", side_effect=lambda text: next(
                    value for name, value in order.items() if text.endswith(name))), \
                mock.patch.object(rada, "run_parallel", side_effect=run_parallel), \
                mock.patch.object(rada, "run_agent", return_value=wynik("wykonane")), \
                mock.patch.object(rada, "save_run",
                                  side_effect=lambda _run_id, record: saved.append(record)), \
                mock.patch.object(rada, "append_memory"):
            cichy(rada.council_run, "zadanie", agents, opts)
        return saved[0]

    def test_zapis_zawiera_mape_anonimizacji_i_punkty(self):
        record = self._uruchom_rade()
        self.assertEqual(record["mapping"], {"A": "alpha", "B": "beta", "C": "gamma"})
        self.assertEqual(record["points"], {"alpha": 0, "beta": 3, "gamma": 6})

    def test_zwyciezce_da_sie_przeliczyc_z_samego_zapisu(self):
        # Symulujemy audytora: dostaje wyłącznie JSON runu (po serializacji)
        # i musi odtworzyć wynik głosowania z surowych głosów + mapy.
        record = json.loads(json.dumps(self._uruchom_rade(), ensure_ascii=False))

        mapping = record["mapping"]
        letters = sorted(mapping)
        rankings = {}
        for juror, res in record["votes"].items():
            parsed = rada.extract_json_block(res["text"])
            rankings[juror] = [str(r).strip().upper() for r in parsed["ranking"]]

        przeliczone = {mapping[l]: p
                       for l, p in rada.tally_votes(letters, rankings).items()}
        self.assertEqual(przeliczone, record["points"])
        self.assertEqual(max(przeliczone, key=przeliczone.get), record["winner"])

    def test_reczny_routing_nie_udaje_glosowania(self):
        opts = SimpleNamespace(mock=True, timeout_exec=1, cwd=".",
                               verify_cmd=None, verify_timeout=10)
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp) / "rada_memory"
            runs_dir = memory_dir / "runs"
            with mock.patch.object(rada, "MEMORY_DIR", memory_dir), \
                    mock.patch.object(rada, "RUNS_DIR", runs_dir), \
                    mock.patch.object(rada, "JOURNAL", memory_dir / "journal.md"):
                cichy(rada.council_run, "@codex zrób test", {"codex": {}}, opts)
            record = json.loads(
                next(runs_dir.glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(record["mapping"], {})
        self.assertIsNone(record["points"])


class Test13_ReviewTruncation(unittest.TestCase):
    """Recenzent musi wiedzieć, czy otrzymał tylko początek raportu."""

    def test_marker_tylko_dla_ucietego_raportu(self):
        krotki = "krótki raport"
        dlugi = "x" * 6001

        self.assertEqual(rada.review_excerpt(krotki), krotki)
        fragment = rada.review_excerpt(dlugi)
        self.assertTrue(fragment.startswith("x" * 6000))
        self.assertIn("pierwsze 6000 z 6001 znaków", fragment)
        self.assertIn("Nie zgłaszaj braku dalszych sekcji", fragment)


if __name__ == "__main__":
    unittest.main(verbosity=2)
