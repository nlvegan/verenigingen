"""#2395: template_variable_validator follows context assignments made in same-module helpers."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import template_variable_validator as v  # noqa: E402

APP = Path(__file__).resolve().parents[3]


def provided(source):
    """Variables the validator believes get_context provides for `source`."""
    validator = v.ModernTemplateValidator(str(APP))
    with tempfile.TemporaryDirectory(dir=APP) as tmp:
        py = Path(tmp) / "page.py"
        py.write_text(source)
        return validator.extract_python_context(py)["variables"]


class TestHelperFollowing(unittest.TestCase):
    def test_helper_receiving_context_positionally_is_followed(self):
        src = "def get_context(context):\n    _add(context)\n\ndef _add(context):\n    context.member_doc = 1\n"
        self.assertIn("member_doc", provided(src))

    def test_helper_with_a_different_parameter_name_is_followed(self):
        src = "def get_context(context):\n    _add(1, ctx=context)\n\ndef _add(x, ctx):\n    ctx['a'] = x\n"
        self.assertIn("a", provided(src))

    def test_helpers_of_helpers_are_followed_and_cycles_stop(self):
        src = (
            "def get_context(context):\n    one(context)\n\n"
            "def one(c):\n    c.first = 1\n    two(c)\n\n"
            "def two(c):\n    c.second = 2\n    one(c)\n"
        )
        self.assertEqual(provided(src) & {"first", "second"}, {"first", "second"})

    def test_update_with_a_dict_in_a_renamed_parameter_helper_is_followed(self):
        src = "def get_context(context):\n    _h(context)\n\ndef _h(ctx):\n    ctx.update({'k': 1})\n"
        self.assertIn("k", provided(src))

    # Controls: each of these has a real assignment in a function that is NOT handed the context.
    def test_helper_not_passed_the_context_does_not_provide_anything(self):
        src = (
            "def get_context(context):\n    _other(1)\n\n"
            "def _other(x):\n    context = {}\n    context.leaked = x\n    context['also_leaked'] = x\n"
        )
        self.assertFalse(provided(src) & {"leaked", "also_leaked"})

    def test_helper_never_called_from_get_context_does_not_provide_anything(self):
        src = "def get_context(context):\n    pass\n\ndef _unused(context):\n    context.orphan = 1\n"
        self.assertNotIn("orphan", provided(src))

    def test_helper_given_something_else_named_context_like_does_not_provide(self):
        src = "def get_context(context):\n    _add(other)\n\ndef _add(context):\n    context.stray = 1\n"
        self.assertNotIn("stray", provided(src))


if __name__ == "__main__":
    unittest.main()
