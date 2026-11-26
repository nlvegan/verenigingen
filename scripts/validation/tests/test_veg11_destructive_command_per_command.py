"""#1151: the veg11 gate is FAIL-CLOSED (maintainer ruling 2026-11-26).

The whole-line match stays the default. A hit is suppressed only when every
command is provably harmless: veg11 appears only as the literal
`bench --site <host>` argument of a non-destructive command, and every
destructive verb is bound to a literal non-veg11 `--site`. Variables, loops,
tables, prose and `bench use` are not provable, so they stay blocked.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "veg11_destructive_command_validator.py"
HOST = "veg11.veganisme.org"


def _veg11_gate_exit_code(line: str) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "doc.md"
        target.write_text(line + "\n")
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(target)], capture_output=True, text=True
        ).returncode


class TestSeparateCommandsAreNotFlagged(unittest.TestCase):
    def test_issue_reproducer_two_correct_commands(self):
        line = (
            "Run tests on a test site: bench --site test_site_1 run-tests --app verenigingen. "
            f"Separately, bench --site {HOST} console is fine."
        )
        self.assertEqual(_veg11_gate_exit_code(line), 0)

    def test_real_instance_with_backticks(self):
        line = (
            "Use e.g. `bench --site test_site_1 run-tests --app verenigingen`. "
            f"Portal render check via `bench --site {HOST} execute x` is inspection-only."
        )
        self.assertEqual(_veg11_gate_exit_code(line), 0)

    def test_verb_command_then_host_command_chained(self):
        line = f"bench --site test_site_1 run-tests && bench --site {HOST} console"
        self.assertEqual(_veg11_gate_exit_code(line), 0)

    def test_host_command_then_verb_command_semicolon(self):
        line = f"bench --site {HOST} backup; bench --site test_site_1 run-tests"
        self.assertEqual(_veg11_gate_exit_code(line), 0)


class TestUnprovableShapesStayBlocked(unittest.TestCase):
    """Every shape the rejected per-segment design (fcbfce2c8) let through."""

    def test_variable_then_use(self):
        self.assertEqual(_veg11_gate_exit_code(f"SITE={HOST}; bench --site $SITE run-tests"), 1)

    def test_export_variable(self):
        self.assertEqual(_veg11_gate_exit_code(f"export SITE={HOST} && bench --site $SITE run-tests"), 1)

    def test_for_loop(self):
        self.assertEqual(
            _veg11_gate_exit_code(f"for s in {HOST} test_site_1; do bench --site $s reinstall --yes; done"), 1
        )

    def test_python_variable(self):
        self.assertEqual(
            _veg11_gate_exit_code(f'site = "{HOST}"; subprocess.run(["bench", "--site", site, "run-tests"])'), 1
        )

    def test_markdown_table_row(self):
        self.assertEqual(_veg11_gate_exit_code(f"| {HOST} | bench run-tests |"), 1)

    def test_make_variable(self):
        self.assertEqual(_veg11_gate_exit_code(f"make SITE={HOST}; bench --site $(SITE) run-tests"), 1)

    def test_prose_split_on_sentence_period(self):
        self.assertEqual(_veg11_gate_exit_code(f"Run bench run-tests. Site: {HOST}"), 1)

    def test_command_substitution(self):
        self.assertEqual(_veg11_gate_exit_code(f"bench --site $(echo {HOST}) run-tests"), 1)
        self.assertEqual(_veg11_gate_exit_code(f"bench --site `echo {HOST}` run-tests"), 1)

    def test_xargs(self):
        self.assertEqual(_veg11_gate_exit_code(f"echo {HOST} | xargs -I{{}} bench --site {{}} run-tests"), 1)

    def test_heredoc_body_line(self):
        text = f"cat <<EOF\nbench --site {HOST} reinstall\nEOF"
        self.assertEqual(_veg11_gate_exit_code(text), 1)

    def test_line_continuation(self):
        self.assertEqual(_veg11_gate_exit_code(f"bench --site {HOST} \\\n  run-tests"), 1)
        self.assertEqual(_veg11_gate_exit_code(f"bench run-tests \\\n  --site {HOST}"), 1)

    def test_chains(self):
        self.assertEqual(_veg11_gate_exit_code(f"cd ~/frappe-bench && bench --site {HOST} reinstall"), 1)
        self.assertEqual(_veg11_gate_exit_code(f"false || bench --site {HOST} run-ui-tests"), 1)
        self.assertEqual(_veg11_gate_exit_code(f"echo y | bench --site {HOST} run-parallel-tests"), 1)
        self.assertEqual(_veg11_gate_exit_code(f"bench --site test_site_1 migrate; bench --site {HOST} run-tests"), 1)

    def test_equals_spelling(self):
        self.assertEqual(_veg11_gate_exit_code(f"bench --site={HOST} run-tests"), 1)

    def test_site_then_verb_and_verb_then_site(self):
        self.assertEqual(_veg11_gate_exit_code(f"bench --site {HOST} run-tests --app verenigingen"), 1)
        self.assertEqual(_veg11_gate_exit_code(f"bench run-tests --site {HOST}"), 1)

    def test_drop_site_positional(self):
        self.assertEqual(_veg11_gate_exit_code(f"bench drop-site {HOST} --force"), 1)

    def test_bench_use_is_not_a_bound_site(self):
        self.assertEqual(_veg11_gate_exit_code(f"bench use {HOST} && bench run-tests"), 1)
        self.assertEqual(_veg11_gate_exit_code(f"bench use {HOST}; bench --site test_site_1 run-tests"), 1)

    def test_prose_verb_before_site(self):
        self.assertEqual(_veg11_gate_exit_code(f"Never run run-tests against {HOST}"), 1)
        self.assertEqual(_veg11_gate_exit_code(f"Use run-tests e.g. on {HOST}"), 1)

    def test_verb_site_is_a_variable_or_quoted(self):
        # a verb bound to a non-literal --site cannot be proved safe
        self.assertEqual(_veg11_gate_exit_code(f"bench --site {HOST} console. bench --site $S run-tests"), 1)
        self.assertEqual(_veg11_gate_exit_code(f'bench --site {HOST} console. bench --site "x" run-tests'), 1)

    def test_verb_with_no_site_binding_next_to_a_safe_host_command(self):
        self.assertEqual(_veg11_gate_exit_code(f"bench --site {HOST} console && bench run-tests"), 1)
        self.assertEqual(_veg11_gate_exit_code(f"bench --site {HOST} console. Then bench reinstall"), 1)

    def test_host_and_verb_in_one_command_even_with_other_literal_site(self):
        self.assertEqual(_veg11_gate_exit_code(f"bench --site test_site_1 run-tests --site {HOST}"), 1)

    def test_one_bound_and_one_unbound_host_mention(self):
        self.assertEqual(_veg11_gate_exit_code(f"bench --site {HOST} console, also {HOST}. bench --site test_site_1 run-tests"), 1)

    @unittest.expectedFailure
    def test_bare_short_form_is_out_of_scope_1146(self):
        # Pinned gap: the gate only recognises the full hostname (#1146).
        self.assertEqual(_veg11_gate_exit_code("| veg11 | bench run-tests |"), 1)


class TestQuotedOrAliasedHostWithDecoyStaysBlocked(unittest.TestCase):
    """Review round 2 (#1151): a bound host that is quoted, assigned, aliased or
    wrapped is not a command in position; a decoy `bench --site test_site_1`
    elsewhere on the line must not launder it."""

    def test_assigned_string_then_expanded(self):
        self.assertEqual(
            _veg11_gate_exit_code(f"V='bench --site {HOST}'; $V reinstall # bench --site test_site_1"), 1
        )
        self.assertEqual(
            _veg11_gate_exit_code(
                f'V="bench --site {HOST}"; $V run-tests --app x # bench --site test_site_1 is the safe form'
            ),
            1,
        )

    def test_alias(self):
        self.assertEqual(
            _veg11_gate_exit_code(f"alias vb='bench --site {HOST}'; vb reinstall # bench --site test_site_1"), 1
        )

    def test_shell_function(self):
        self.assertEqual(
            _veg11_gate_exit_code(
                f'vb() {{ bench --site {HOST} "$@"; }}; vb run-tests --app x # bench --site test_site_1'
            ),
            1,
        )

    def test_array_variable(self):
        self.assertEqual(
            _veg11_gate_exit_code(f'CMD=(bench --site {HOST}); "${{CMD[@]}}" reinstall # bench --site test_site_1'),
            1,
        )

    def test_single_ampersand_is_a_separator_not_a_cover(self):
        self.assertEqual(
            _veg11_gate_exit_code(f"V='bench --site {HOST}'; $V reinstall & bench --site test_site_1 console"), 1
        )

    def test_verb_fed_as_data_through_xargs(self):
        # Round-2 review: the verb segment held `bench --site test_site_1` as echo DATA, and
        # xargs then ran `bench --site <host> reinstall`.
        self.assertEqual(
            _veg11_gate_exit_code(
                f"echo reinstall bench --site test_site_1 | cut -d' ' -f1 | xargs bench --site {HOST}"
            ),
            1,
        )

    def test_redirect_ampersand_does_not_split_a_command(self):
        # `2>&1` is a redirect, not a separator: it must not cut host from verb.
        self.assertEqual(
            _veg11_gate_exit_code(f"bench --site test_site_1 reinstall 2>&1 bench --site {HOST}"), 1
        )


class TestEachSuppressionRuleIsPinned(unittest.TestCase):
    """Each rule below was found removable with every other test green."""

    def test_veg11_prefix_site_is_not_a_safe_literal(self):
        # `--site veg11` is veg11 too; without the "veg11" check the verb
        # command is accepted as bound to a literal non-veg11 site.
        self.assertEqual(_veg11_gate_exit_code(f"bench --site veg11 reinstall; bench --site {HOST} console"), 1)

    def test_longer_hostname_is_a_different_host_so_allowed(self):
        # Direction pinned: `<host>.evil.com` / `<host>-old` name another host,
        # so the host lookahead leaves them alone.
        self.assertEqual(
            _veg11_gate_exit_code(f"Compare {HOST}.evil.com notes; bench --site test_site_1 run-tests"), 0
        )
        self.assertEqual(_veg11_gate_exit_code(f"See {HOST}-old docs; bench --site test_site_1 run-tests"), 0)

    def test_sentence_period_after_host_is_still_the_host(self):
        # control for the lookahead: a trailing sentence period is not a suffix
        self.assertEqual(_veg11_gate_exit_code(f"Site {HOST}. bench --site test_site_1 run-tests"), 1)

    def test_eg_and_ie_do_not_split_a_command(self):
        self.assertEqual(
            _veg11_gate_exit_code(f"bench --site {HOST} e.g. bench --site test_site_1 run-tests"), 1
        )
        self.assertEqual(
            _veg11_gate_exit_code(f"bench --site {HOST} i.e. bench --site test_site_1 run-tests"), 1
        )


class TestProvablySafeShapesAllowed(unittest.TestCase):
    def test_no_host_at_all(self):
        self.assertEqual(_veg11_gate_exit_code("bench --site test_site_1 run-tests --app verenigingen"), 0)

    def test_host_with_non_destructive_verbs_only(self):
        for verb in ("console", "mariadb", "migrate", "backup"):
            self.assertEqual(_veg11_gate_exit_code(f"bench --site {HOST} {verb}"), 0, verb)

    def test_equals_spelling_safe(self):
        self.assertEqual(_veg11_gate_exit_code(f"bench --site={HOST} migrate; bench --site=test_site_2 run-tests"), 0)

    def test_two_chained_commands_pipe_or_and(self):
        self.assertEqual(_veg11_gate_exit_code(f"bench --site test_site_1 run-tests | tee out.log && bench --site {HOST} console"), 0)

    def test_single_ampersand_separates_two_correct_commands(self):
        self.assertEqual(_veg11_gate_exit_code(f"bench --site {HOST} console & bench --site test_site_1 run-tests"), 0)

    def test_dotted_literal_site(self):
        self.assertEqual(_veg11_gate_exit_code(f"bench --site test.localhost run-tests. bench --site {HOST} backup"), 0)


if __name__ == "__main__":
    unittest.main()
