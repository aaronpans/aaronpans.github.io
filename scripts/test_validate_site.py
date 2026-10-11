"""Regression checks using in-memory mutations; never changes site files.

Run: python3 -m unittest discover -s scripts -p 'test_*.py' -v
"""
import contextlib
import io
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / 'scripts/validate_site.py'
EN_LINK = '<link rel="alternate" hreflang="en" href="https://aaronpans.github.io/en/">'
ZH_LINK = '<link rel="alternate" hreflang="zh-CN" href="https://aaronpans.github.io/">'


class LanguageValidationTests(unittest.TestCase):
    def validate(self, file=None, old=None, new=None):
        original_read = Path.read_text
        target = ROOT / file if file else None
        if target:
            self.assertEqual(original_read(target).count(old), 1,
                             'Mutation fixture must match exactly once')

        def read(path, *args, **kwargs):
            source = original_read(path, *args, **kwargs)
            return source.replace(old, new, 1) if path == target else source

        output = io.StringIO()
        status = 0
        with patch.object(Path, 'read_text', read), contextlib.redirect_stdout(output):
            try:
                runpy.run_path(str(VALIDATOR), run_name='__main__')
            except SystemExit as exc:
                status = exc.code
        return status, output.getvalue()

    def test_current_site_passes(self):
        status, output = self.validate()
        self.assertEqual(status, 0, output)
        self.assertIn('PASS:', output)

    def test_bad_language_links_are_rejected(self):
        cases = [
            ('duplicate', 'index.html', EN_LINK, EN_LINK + EN_LINK, 'duplicate hreflang'),
            ('self', 'en/index.html', EN_LINK, '', 'missing self-referencing language alternate'),
            ('return', 'en/index.html', ZH_LINK, '', 'missing reciprocal hreflang'),
            ('relative', 'index.html', EN_LINK,
             EN_LINK.replace('https://aaronpans.github.io/en/', '/en/'),
             'hreflang URL must be absolute'),
            ('missing', 'index.html', EN_LINK,
             EN_LINK.replace('/en/', '/missing-language-regression-fixture/'),
             'hreflang target missing'),
            ('canonical', 'index.html', EN_LINK,
             EN_LINK.replace('/en/', '/en/index.html'),
             'hreflang target is not canonical'),
            ('language', 'index.html', EN_LINK,
             EN_LINK.replace('hreflang="en"', 'hreflang="fr"'),
             'hreflang/target lang mismatch'),
        ]
        for name, file, old, new, diagnostic in cases:
            with self.subTest(case=name):
                status, output = self.validate(file, old, new)
                self.assertEqual(status, 1, output)
                self.assertIn(diagnostic, output)


if __name__ == '__main__':
    unittest.main()
