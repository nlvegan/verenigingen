"""#2404 / #2408: template_variable_validator guard detection and 'provided' extraction."""

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


def null_risks(template):
    """Variable names the null-reference check flags in `template`."""
    validator = v.ModernTemplateValidator(str(APP))
    with tempfile.TemporaryDirectory(dir=APP) as tmp:
        html = Path(tmp) / "page.html"
        html.write_text(template)
        return {i.variable_name for i in validator.check_null_reference_risks(html)}


class TestOnlyWritesAreProvided(unittest.TestCase):
    def test_a_read_provides_nothing(self):
        self.assertNotIn("missing", provided("def get_context(context):\n    x = context.missing\n"))

    def test_a_subscript_read_provides_nothing(self):
        self.assertNotIn("missing", provided("def get_context(context):\n    x = context['missing']\n"))

    def test_ctx_get_provides_neither_get_nor_its_key(self):
        got = provided("def get_context(context):\n    x = context.get('foo')\n")
        self.assertFalse(got & {"get", "foo"})

    def test_a_branch_that_can_never_run_provides_nothing(self):
        src = "def get_context(context):\n    if False:\n        context.dead = 1\n    else:\n        context.live = 1\n"
        got = provided(src)
        self.assertNotIn("dead", got)
        self.assertIn("live", got)

    def test_code_after_return_provides_nothing(self):
        src = "def get_context(context):\n    context.before = 1\n    return\n    context.after = 2\n"
        got = provided(src)
        self.assertIn("before", got)
        self.assertNotIn("after", got)

    def test_a_write_to_a_reassigned_parameter_provides_nothing(self):
        src = "def get_context(context):\n    context.real = 1\n    context = {}\n    context.local = 1\n"
        got = provided(src)
        self.assertIn("real", got)
        self.assertNotIn("local", got)

    # Controls: the writes the fix must keep seeing.
    def test_plain_conditional_and_subscript_writes_still_count(self):
        src = (
            "def get_context(context):\n    context.a = 1\n    context['b'] = 2\n"
            "    if context.a:\n        context.c = 3\n    context.d += 1\n"
        )
        self.assertEqual(provided(src) & {"a", "b", "c", "d"}, {"a", "b", "c", "d"})

    def test_update_with_a_dict_and_with_keywords_counts(self):
        src = "def get_context(context):\n    context.update({'k': 1})\n    context.update(j=2)\n"
        self.assertEqual(provided(src) & {"k", "j"}, {"k", "j"})

    def test_a_wrapping_rebind_keeps_later_writes(self):
        # my_teams.py: context = frappe._dict(context), then context.teams = ...
        src = "def get_context(context):\n    context = dict(context)\n    context.teams = 1\n"
        self.assertIn("teams", provided(src))

    def test_a_loop_over_a_module_tuple_provides_each_key(self):
        # mollie_checkout.py: for key in expected_keys: context[key] = ...
        src = "KEYS = ('amount', 'title')\n\ndef get_context(context):\n    for key in KEYS:\n        context[key] = 1\n"
        self.assertEqual(provided(src) & {"amount", "title"}, {"amount", "title"})

    def test_a_loop_over_a_literal_provides_each_key(self):
        src = "def get_context(context):\n    for k in ['x', 'y']:\n        context[k] = 1\n"
        self.assertEqual(provided(src) & {"x", "y"}, {"x", "y"})

    def test_a_subscript_by_an_unknown_name_provides_nothing(self):
        self.assertFalse(provided("def get_context(context):\n    context[some_var] = 1\n") & {"some_var"})


class TestHelperParameters(unittest.TestCase):
    def test_a_keyword_only_parameter_is_followed(self):
        src = "def get_context(context):\n    _h(ctx=context)\n\ndef _h(*, ctx):\n    ctx.kwonly = 1\n"
        self.assertIn("kwonly", provided(src))

    def test_a_positional_only_parameter_is_followed(self):
        src = "def get_context(context):\n    _h(context)\n\ndef _h(ctx, /):\n    ctx.posonly = 1\n"
        self.assertIn("posonly", provided(src))

    def test_a_helper_called_with_two_bindings_is_read_for_both(self):
        src = (
            "def get_context(context):\n    _h(context, 1)\n    _h(1, context)\n\n"
            "def _h(a, b):\n    a.first = 1\n    b.second = 1\n"
        )
        self.assertEqual(provided(src) & {"first", "second"}, {"first", "second"})


class TestIfGuards(unittest.TestCase):
    def test_a_three_term_guard_with_a_comparison_protects(self):
        # dues-invoice-manager.html:154/202
        tpl = (
            "{% if ws and ws.cm and ws.cm.total > 0 %}\n"
            "<p></p>\n"
            "{{ ws.cm.early.count }}\n"
            "{% endif %}\n"
        )
        self.assertNotIn("ws", null_risks(tpl))

    def test_the_guard_still_protects_far_below_it(self):
        tpl = "{% if ws and ws.a.b > 0 %}\n" + "<p>x</p>\n" * 80 + "{{ ws.a.b.c }}\n{% endif %}\n"
        self.assertNotIn("ws", null_risks(tpl))

    def test_a_nested_if_does_not_hide_the_outer_guard(self):
        tpl = "{% if ws and ws.a %}\n<p></p>\n{% if other %}\n{% endif %}\n{{ ws.a.b.c }}\n{% endif %}\n"
        self.assertNotIn("ws", null_risks(tpl))

    def test_an_elif_condition_replaces_the_guard(self):
        tpl = "{% if x %}\n{% elif ws and ws.a %}\n<p></p>\n{{ ws.a.b.c }}\n{% endif %}\n"
        self.assertNotIn("ws", null_risks(tpl))

    # Controls: each of these must still be flagged.
    def test_an_unguarded_deep_access_is_flagged(self):
        self.assertIn("ws", null_risks("{{ ws.a.b.c }}\n"))

    def test_after_the_endif_it_is_flagged(self):
        tpl = "{% if ws and ws.a and ws.a.n > 0 %}\n<p></p>\n{% endif %}\n{{ ws.a.b.c }}\n"
        self.assertIn("ws", null_risks(tpl))

    def test_the_else_arm_is_flagged(self):
        tpl = "{% if ws and ws.a and ws.a.n > 0 %}\n<p></p>\n{% else %}\n{{ ws.a.b.c }}\n{% endif %}\n"
        self.assertIn("ws", null_risks(tpl))

    def test_an_or_chain_does_not_protect(self):
        # blank line: the legacy previous-line check would otherwise mask the arm
        tpl = "{% if ws or ws.a %}\n<p></p>\n{{ ws.a.b.c }}\n{% endif %}\n"
        self.assertIn("ws", null_risks(tpl))

    def test_an_or_around_the_guarded_conjuncts_does_not_protect(self):
        tpl = "{% if flag or (ws and ws.a) %}\n<p></p>\n{{ ws.a.b.c }}\n{% endif %}\n"
        self.assertIn("ws", null_risks(tpl))

    def test_a_negated_or_not_equal_conjunct_does_not_protect(self):
        for cond in ("not ws and flag", "flag and ws != 1", "flag and wsx"):
            with self.subTest(cond=cond):
                self.assertIn("ws", null_risks("{% if " + cond + " %}\n<p></p>\n{{ ws.a.b.c }}\n{% endif %}\n"))

    def test_a_guard_on_a_different_variable_does_not_protect(self):
        tpl = "{% if other and other.a %}\n{{ ws.a.b.c }}\n{% endif %}\n"
        self.assertIn("ws", null_risks(tpl))


if __name__ == "__main__":
    unittest.main()
