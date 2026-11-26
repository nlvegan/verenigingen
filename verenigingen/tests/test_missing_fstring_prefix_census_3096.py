"""
#3096: plain string literals that look like f-strings but lack the ``f`` prefix.

A literal such as ``"eBoekhouden Import {mutation_id}"`` is a perfectly valid
str, so nothing fails: the braces just reach the Journal Entry description, a
metric key or an HTML attribute verbatim.

Census: an AST walk over production code (``verenigingen/`` minus tests, and
``scripts/``) that fails on any non-f str constant holding a ``{expression}``
placeholder whose every name is in scope at that line. Excluded, because they
are legitimately plain: ``.format()`` receivers (directly, through ``_()``, or
through a variable that is ``.format()``-ed later), bare docstrings,
dict/set-looking braces, and anything whose names are not in scope.

``stock_migration.py`` is excluded here only because PR #3105 (issue 2693) owns
its four sites; drop the exclusion once that PR is merged.
"""

import ast
import os
import re
import unittest

import frappe

import verenigingen

_PLACEHOLDER_3096 = re.compile(r"(?<!\{)\{([^{}\n]+?)\}(?!\})")
_OWNED_ELSEWHERE_3096 = ("utils/migration/stock_migration.py",)  # PR #3105
_FORMAT_NAMES_3096 = ("_", "__", "_lt")


def _scope_names_3096(node):
    names = set()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        a = node.args
        names |= {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}
        names |= {x.arg for x in (a.vararg, a.kwarg) if x}
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            names.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            names.add(n.name)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            names |= {(al.asname or al.name).split(".")[0] for al in n.names}
    return names


def _placeholder_roots_3096(value):
    """Names used by the {expr} placeholders, or None if any brace is not an expression."""
    roots = set()
    for raw in _PLACEHOLDER_3096.findall(value):
        parsed = None
        for cand in (raw, re.sub(r"![rsa]$", "", raw), re.sub(r"(![rsa])?:[^:'\"\]\)]*$", "", raw)):
            try:
                parsed = ast.parse(cand, mode="eval")
                break
            except SyntaxError:
                continue
        if parsed is None or isinstance(parsed.body, (ast.Dict, ast.Set)):
            return None
        used = {x.id for x in ast.walk(parsed) if isinstance(x, ast.Name)}
        if not used:
            return None
        roots |= used
    return roots or None


def _is_format_template_3096(node, parent, parents):
    if isinstance(parent, (ast.JoinedStr, ast.FormattedValue, ast.Expr)):
        return True
    if isinstance(parent, ast.Attribute) and parent.attr == "format":
        return True
    if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name) and parent.func.id in _FORMAT_NAMES_3096:
        up = parents.get(parent)
        return isinstance(up, ast.Attribute) and up.attr == "format"
    if isinstance(parent, ast.Assign) and len(parent.targets) == 1 and isinstance(parent.targets[0], ast.Name):
        var, fn = parent.targets[0].id, parent
        while fn is not None and not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            fn = parents.get(fn)
        return any(
            isinstance(c, ast.Call)
            and isinstance(c.func, ast.Attribute)
            and c.func.attr == "format"
            and isinstance(c.func.value, ast.Name)
            and c.func.value.id == var
            for c in ast.walk(fn)
        )
    return False


def find_missing_fstring_prefix_3096(source):
    """Return [(lineno, snippet)] for plain literals carrying in-scope {placeholders}."""
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    module_names = set()
    for n in tree.body:
        module_names |= {n.name} if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else _scope_names_3096(n)
    builtin_names = set(dir(__builtins__) if not isinstance(__builtins__, dict) else __builtins__)
    hits = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Constant) and isinstance(n.value, str)):
            continue
        roots = _placeholder_roots_3096(n.value) if "{" in n.value else None
        if not roots or _is_format_template_3096(n, parents.get(n), parents):
            continue
        scope, up = set(module_names), parents.get(n)
        while up is not None:
            if isinstance(up, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                scope |= _scope_names_3096(up)
            up = parents.get(up)
        if roots - builtin_names <= scope:
            hits.append((n.lineno, n.value.strip()[:70].replace("\n", " ")))
    return hits


def _production_files_3096():
    pkg = os.path.dirname(verenigingen.__file__)
    for root in (pkg, os.path.join(os.path.dirname(pkg), "scripts")):
        for base, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in ("node_modules", "tests", "__pycache__")]
            for f in files:
                path = os.path.join(base, f)
                if f.endswith(".py") and not path.endswith(_OWNED_ELSEWHERE_3096):
                    yield path


class TestMissingFstringPrefixCensus3096(unittest.TestCase):
    def test_no_production_literal_has_unformatted_placeholders(self):
        found = []
        for path in _production_files_3096():
            with open(path, encoding="utf8") as fh:
                try:
                    hits = find_missing_fstring_prefix_3096(fh.read())
                except SyntaxError:
                    continue
            found += [f"{os.path.relpath(path, os.path.dirname(os.path.dirname(verenigingen.__file__)))}:{ln}: {snip}" for ln, snip in hits]
        self.assertEqual(found, [], "plain literals with {placeholders} that need an f prefix:\n" + "\n".join(found))

    def test_control_scanner_catches_a_seeded_instance(self):
        seeded = (
            "def f(entry, mutation_id):\n"
            "    a = {'voucher': '{entry.voucher_type} {entry.voucher_no}'}\n"
            "    b = dict().get('d', 'Import {mutation_id}')\n"
            "    c = '{entry.get(\"x\")} y'\n"
            "    return a\n"
        )
        lines = sorted(ln for ln, _ in find_missing_fstring_prefix_3096(seeded))
        self.assertEqual(lines, [2, 3, 4])

    def test_control_scanner_catches_placeholders_starting_with_a_quote(self):
        # {', '.join(x)} and {','.join(...)} start with a quote, not a letter (review of #3096)
        seeded = (
            "def f(slow, names):\n"
            "    a = \"Optimize: {', '.join(slow)}.\"\n"
            "    b = \"\"\"DELETE FROM t WHERE name IN ({','.join(['%s'] * len(names))})\"\"\"\n"
            "    return a, b\n"
        )
        self.assertEqual(sorted(ln for ln, _ in find_missing_fstring_prefix_3096(seeded)), [2, 3])

    def test_control_scanner_ignores_legitimate_templates(self):
        legit = (
            "from frappe import _\n"
            "def f(name, n):\n"
            "    \"\"\"doc {name}\"\"\"\n"
            "    a = '{name}'.format(name=name)\n"
            "    b = _('Hi {name}').format(name=name)\n"
            "    sql = 'SELECT {cols}'\n"
            "    cols = 1\n"
            "    sql = sql.format(cols=cols)\n"
            "    c = f'{name}'\n"
            "    d = '{\"k\": 1}'\n"
            "    e = '{other}'\n"  # `other` not in scope: not a missing-prefix bug
            "    return a\n"
        )
        self.assertEqual(find_missing_fstring_prefix_3096(legit), [])


class TestFormattedLiteralBehaviour3096(unittest.TestCase):
    """Each test fails on develop because the literal reached the output unformatted."""

    def test_api_metrics_are_keyed_per_endpoint(self):
        from verenigingen.utils.performance_dashboard import PerformanceMetrics

        metrics = PerformanceMetrics()
        metrics.record_api_call("ep_one", 5.0, True)
        metrics.record_api_call("ep_two", 7.0, True)
        self.assertEqual(metrics.metrics["api_ep_one_time"], [5.0])
        self.assertEqual(metrics.metrics["api_ep_two_time"], [7.0])
        self.assertNotIn("api_{endpoint}_time", metrics.metrics)

    def test_db_metrics_are_keyed_per_query_type(self):
        from verenigingen.utils.performance_dashboard import PerformanceMetrics

        metrics = PerformanceMetrics()
        metrics.record_database_query("select_x", 3.0, row_count=9)
        self.assertEqual(metrics.metrics["db_select_x_time"], [3.0])
        self.assertEqual(metrics.metrics["db_select_x_rows"], [9])

    def test_query_optimization_suggestion_names_the_query(self):
        from verenigingen.utils.performance_dashboard import PerformanceDashboard

        dashboard = PerformanceDashboard()
        dashboard.metrics.record_database_query("db_slow_report", 99999.0, row_count=1)
        suggestions = dashboard.get_optimization_suggestions()["query_optimizations"]
        self.assertEqual(len(suggestions), 1)
        self.assertIn("db_slow_report", suggestions[0])
        self.assertIn("99999.00ms", suggestions[0])
        self.assertNotIn("{", suggestions[0])

    def test_assign_buttons_carry_the_member_and_chapter(self):
        from verenigingen.verenigingen.report.members_without_chapter.members_without_chapter import (
            get_action_buttons,
        )

        html = get_action_buttons("MEM-3096", "Chapter Utrecht")
        self.assertEqual(html.count('data-member="MEM-3096"'), 2)
        self.assertIn('data-chapter="Chapter Utrecht"', html)
        self.assertIn('title="Assign to Chapter Utrecht"', html)
        self.assertNotIn("{member_name}", html)
        self.assertNotIn("{suggested_chapter}", html)

    def test_assign_buttons_escape_free_text_chapter_names(self):
        from verenigingen.verenigingen.report.members_without_chapter.members_without_chapter import (
            get_action_buttons,
        )

        html = get_action_buttons("MEM-3096", 'x"><script>alert(1)</script>')
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_transaction_type_reason_names_the_type(self):
        from verenigingen.e_boekhouden.utils.eboekhouden_transaction_type_mapper import (
            simplify_migration_process,
        )

        result = simplify_migration_process({"type": 1})
        self.assertEqual(result["reason"], "Direct mapping from E-boekhouden type: 1")

    def test_dutch_account_reasons_name_the_match(self):
        from verenigingen.utils.dutch_account_patterns import (
            DUTCH_ACCOUNT_PATTERNS,
            GROUP_CODE_PATTERNS,
            suggest_account_type_from_dutch,
        )

        pattern = next(iter(DUTCH_ACCOUNT_PATTERNS))
        self.assertEqual(
            suggest_account_type_from_dutch(f"xx {pattern} xx")[2], f"Name contains '{pattern}'"
        )
        prefix = next(iter(GROUP_CODE_PATTERNS))
        reason = suggest_account_type_from_dutch("zzzz-no-name-match", prefix + "99")[2]
        self.assertEqual(reason, f"Group code starts with {prefix}")

    def test_dutch_name_self_test_labels_its_inputs(self):
        import inspect

        from verenigingen.utils.dutch_name_utils import test_dutch_name_formatting

        # The endpoint is @development_only_api (refused when developer_mode=0, as in CI), so
        # call the undecorated body.
        labels = [r["input"] for r in inspect.unwrap(test_dutch_name_formatting)()["test_results"]]
        self.assertIn("first='Jan', middle='None', tussen='van', last='Berg'", labels)

    def test_missing_transaction_type_error_log_carries_the_mutation_id(self):
        from verenigingen.e_boekhouden.utils.eboekhouden_transaction_type_mapper import (
            simplify_migration_process,
        )

        marker = "MUT-3096-NOTYPE"
        simplify_migration_process({"MutatieNr": marker})
        # Error Log is MyISAM (non-transactional), so these rows survive rollback: delete them.
        rows = frappe.get_all(
            "Error Log",
            filters={"error": ["like", f"%{marker}%"]},
            fields=["name", "method", "error"],
        )
        try:
            self.assertEqual(len(rows), 1, rows)
            self.assertEqual(rows[0].method, "E-Boekhouden Migration")
            self.assertEqual(rows[0].error, f"No transaction type found in mutation {marker}")
        finally:
            for row in rows:
                frappe.delete_doc("Error Log", row.name, force=True)
