"""Testy artefaktu gry NEFARIN: Core Defense (game/index.html)."""
import os
import unittest

GAME_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game", "index.html")


class TestGameArtifact(unittest.TestCase):
    def _read(self):
        with open(GAME_PATH, encoding="utf-8") as f:
            return f.read()

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(GAME_PATH), "brak pliku game/index.html")

    def test_contains_canvas(self):
        self.assertIn("<canvas", self._read().lower(), "brak elementu <canvas>")

    def test_contains_script(self):
        self.assertIn("<script", self._read().lower(), "brak elementu <script>")

    def test_no_external_urls(self):
        content = self._read().lower()
        self.assertNotIn("http://", content, "plik zawiera odwolanie http://")
        self.assertNotIn("https://", content, "plik zawiera odwolanie https://")


if __name__ == "__main__":
    unittest.main()
