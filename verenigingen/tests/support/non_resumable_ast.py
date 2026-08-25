"""The AST predicates two non-resumable ratchets both need.

`test_termination_non_resumable_errors` (#470) scans one package for catch-alls that would
record a 1205/1213 and carry on. `test_savepoint_rollback_cannot_mask_the_error` (#561) scans
every production file for savepoint rollbacks that can replace the error being handled. They
ask the same two questions of a handler, and the duplicate-helper ratchet reported the second
copy of ``_reraises_non_resumable`` the moment it existed -- which is the same reason
``non_resumable_errors.py`` exists next to this file.

The rule they share is deliberately the STRICTER of the two originals. #470's version required
``len(body) == 1``, which already rejected a trailing ``return``; this also rejects
``raise Wrapper(e)``, because replacing the exception is #561's own defect written by hand --
a guard that re-raises a different class leaves every caller keyed on the original type failing
exactly as it does after a 1305.
"""

import ast

CATCH_ALLS = ("Exception", "BaseException")
GUARD_NAME = "NON_RESUMABLE_DB_ERRORS"
GUARD_CLASSES = frozenset({"QueryDeadlockError", "QueryTimeoutError"})


def _handler_types(handler):
    if handler.type is None:
        return []
    return handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]


def catches_bare_exception(handler):
    """`except:`, `except Exception:`, `except (ValueError, Exception):` -- all catch-alls."""
    if handler.type is None:
        return True
    return any(isinstance(t, ast.Name) and t.id in CATCH_ALLS for t in _handler_types(handler))


def names_the_non_resumable_classes(handler):
    """Accepts the tuple by name, through a module alias, or spelled out as both classes.

    application_payments names the two classes directly and on purpose, so a matcher that
    only knew the tuple's bare name reported the one site that got this right as unguarded.
    """
    named = {ast.unparse(t).rsplit(".", 1)[-1] for t in _handler_types(handler)}
    return GUARD_NAME in named or GUARD_CLASSES <= named


def reraises_unconditionally(handler):
    """The handler cannot swallow and cannot substitute.

    Three conditions, each of which was a hole in one of the two originals:

    * the LAST statement re-raises -- not "contains a raise somewhere", because
      mt940_import re-raised inside a nested handler around its own rollback and then
      returned a dict, which swallows just as thoroughly;
    * it is a BARE ``raise`` -- see the module docstring;
    * no ``return`` anywhere, or an earlier branch swallows conditionally while the last
      line still reads like a re-raise.
    """
    if not handler.body or not isinstance(handler.body[-1], ast.Raise):
        return False
    if handler.body[-1].exc is not None:
        return False
    return not any(isinstance(node, ast.Return) for node in ast.walk(handler))


def reraises_non_resumable(handler):
    """A preceding clause that names the class AND genuinely re-raises it."""
    return names_the_non_resumable_classes(handler) and reraises_unconditionally(handler)
