"""#1181: the shared snippet guard must reject an unparseable snippet and accept the same one correctly spelled."""
import tempfile
import unittest
from pathlib import Path

try:
    from snippet_parse_guard import assert_snippet_parses, write_py_snippet
except ImportError:  # run by dotted name: python -m unittest scripts.validation.tests.<module>
    from .snippet_parse_guard import assert_snippet_parses, write_py_snippet

_VALID = "def f():\n    x = 1\n    return x\n"
_BROKEN_INDENTATION = "def f():\n    x = 1\n      return x\n"


class SnippetParseGuardTest(unittest.TestCase):
    def test_a_correctly_spelled_snippet_is_written(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ok.py"
            write_py_snippet(p, _VALID)
            self.assertEqual(_VALID, p.read_text())

    def test_an_unparseable_snippet_raises_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.py"
            with self.assertRaises(AssertionError) as ctx:
                write_py_snippet(p, _BROKEN_INDENTATION)
            self.assertIn("does not parse", str(ctx.exception))
            self.assertFalse(p.exists())

    def test_intentionally_invalid_is_an_explicit_opt_out(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.py"
            write_py_snippet(p, _BROKEN_INDENTATION, intentionally_invalid=True)
            self.assertEqual(_BROKEN_INDENTATION, p.read_text())

    def test_intentionally_invalid_must_really_be_invalid(self):
        # Review nit: if someone "fixes" an intentionally-invalid snippet, the test that
        # uses it silently stops exercising the scanner's skip-unparseable path.
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ok.py"
            with self.assertRaises(AssertionError):
                write_py_snippet(p, _VALID, intentionally_invalid=True)
            self.assertFalse(p.exists())

    def test_assert_snippet_parses_rejects_broken_source(self):
        assert_snippet_parses(_VALID)
        with self.assertRaises(AssertionError):
            assert_snippet_parses(_BROKEN_INDENTATION)


if __name__ == "__main__":
    unittest.main()
