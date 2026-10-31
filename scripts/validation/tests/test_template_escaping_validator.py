"""Unit tests for scripts/validation/template_escaping_validator.py (#1890)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import template_escaping_validator as v  # noqa: E402

REL = "verenigingen/templates/pages/example.html"


def found(source, rel=REL):
    return [text for _ln, text in v.find_unescaped(source, rel)]


class TestFlagged(unittest.TestCase):
    def test_bare_attribute_is_flagged(self):
        self.assertEqual(found("<p>{{ member.full_name }}</p>"), ["member.full_name"])

    def test_dynamic_translation_and_format_are_flagged(self):
        self.assertEqual(len(found("{{ _(label) }} {{ _('Hi {0}').format(name) }}")), 2)

    def test_conditional_with_a_bare_branch_is_flagged(self):
        self.assertEqual(len(found("{{ 'x' if ok else member.name }}")), 1)

    def test_safe_without_prior_escape_is_flagged(self):
        self.assertEqual(len(found("{{ blob|safe }} {{ x|replace('a','b')|safe }}")), 2)

    def test_whitespace_control_does_not_hide_a_finding(self):
        self.assertEqual(found("{{- member.name -}}"), ["member.name"])

    def test_unparseable_output_is_a_finding(self):
        self.assertEqual(len(found("{{ a b }}")), 1)

    def test_e_inside_a_script_block_is_flagged(self):
        """C1 of the #1890 review: |e turns the JSON's quotes into &#34; and breaks the script."""
        self.assertEqual(len(found("<script>var a = {{ data_json|e }};</script>")), 1)
        self.assertEqual(len(found("<script>var a = '{{ name|e }}';</script>")), 1)

    def test_script_state_ends_at_the_closing_tag(self):
        self.assertEqual(found("<script>var a = 1;</script><p>{{ name|e }}</p>"), [])

    def test_script_state_survives_jinja_blocks_inside_the_script(self):
        src = "<script>{% if x %}var a = {{ name|e }};{% endif %}</script>"
        self.assertEqual(len(found(src)), 1)

    def test_any_output_in_an_on_handler_is_flagged(self):
        self.assertEqual(len(found("""<a onclick="go('{{ x|e }}')">""")), 1)
        self.assertEqual(len(found("""<a onclick="go({{ x|tojson }})">""")), 1)
        self.assertEqual(len(found("""<a onclick='go("{{ x|e }}")'>""")), 1)

    def test_a_data_attribute_is_ordinary_html(self):
        self.assertEqual(found("""<a data-x="{{ x|e }}" onclick="go(this.dataset.x)">"""), [])

    def test_unescaping_after_the_escape_is_flagged(self):
        self.assertEqual(len(found("{{ x|e|replace('&lt;','<')|safe }}")), 1)
        self.assertEqual(len(found("{{ x|forceescape|replace('a','<script>')|safe }}")), 1)

    def test_macro_call_with_an_argument_is_flagged(self):
        self.assertEqual(len(found("{{ chapter_button(user_value) }}")), 1)
        self.assertEqual(found("{{ chapter_button() }}"), [])

    def test_unlisted_macro_call_is_flagged(self):
        self.assertEqual(len(found("{{ render_thing(x) }}")), 1)


class TestAccepted(unittest.TestCase):
    def test_escaped_forms(self):
        src = (
            "{{ a|e }} {{ a|escape }} {{ a|urlencode|e }} {{ (a or b)|e }} "
            "{{ a|default('x')|e }} {{ a|tojson }} {{ a|tojson|safe }}"
        )
        self.assertEqual(found(src), [])

    def test_script_accepts_tojson_numbers_and_literals(self):
        src = "<script>var a = {{ x|default('')|tojson }}, b = {{ n|int }}, c = {{ _('Static') }};</script>"
        self.assertEqual(found(src), [])

    def test_numbers_literals_and_static_translations(self):
        self.assertEqual(found("{{ n|int }} {{ n|float }} {{ rows|length }} {{ 5 }} {{ _('Static') }}"), [])

    def test_super_and_allowlisted_macro(self):
        self.assertEqual(found("{{ super() }}{{ brand_css() }}"), [])

    def test_conditional_of_safe_branches(self):
        self.assertEqual(found("{{ a|tojson if a else '{}' }} {{ _('Yes') if ok else _('No') }}"), [])

    def test_comments_and_raw_blocks_are_not_scanned(self):
        self.assertEqual(found("{# {{ a }} #}{% raw %}{{ vue.value }}{% endraw %}"), [])

    def test_allowlisted_expression_only_matches_its_own_file(self):
        rel, text = next(iter(v.ALLOWED_EXPRESSIONS))
        self.assertEqual(found("{{ %s }}" % text, rel), [])
        self.assertEqual(len(found("{{ %s }}" % text, REL)), 1)


class TestTree(unittest.TestCase):
    def test_whole_tree_is_clean(self):
        findings = [f for p in v.template_files() for f in v.check_file(p)]
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
