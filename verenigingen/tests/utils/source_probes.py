"""AST probes for tests that read the app's own source.

Companion to `paths.APP_ROOT`: that module answers "which directory do I scan",
this one answers "what does this file do". `called_names` lives here rather than
in each caller because two source guards needed the same walk in the same commit
and the duplicate-helper ratchet caught the second copy -- correctly. Two copies
of a call-form walk drift the moment one of them learns about a form the other
does not.
"""

import ast


def called_names(tree: ast.Module) -> set:
    """Every function name CALLED anywhere in `tree`.

    Both the `Name` form (`ensure_root_territory()`) and the `Attribute` form
    (`self._load_fixture_file(...)`), because the setup calls these guards look
    for are written each way.

    Deliberately flat: it answers "is this called anywhere in this file", NOT
    "is it called on the path that needs it". A guard built on it inherits that
    limit and has to say so -- both current callers do.
    """
    called = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name:
            called.add(name)
    return called
