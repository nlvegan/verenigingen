"""Shared helpers for static/structural tests that scan this app's `.js` source.

Extracted so the JS-scanning tests agree on one comment-stripping definition
rather than each reimplementing it. Two independent copies in the same PR
(`test_js_form_on_registration_targets.py` and
`test_js_field_writes_match_schema.py`) is exactly how they drift -- see the
PR #1263 review round that asked for this consolidation.
"""

import re

_BLOCK_COMMENT_PATTERN = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_PATTERN = re.compile(r"//[^\n]*")


def strip_js_comments(content):
    """Remove `/* block */` and `// line` comments from JS source text.

    Good enough for these repo-local static checks (which only care whether a
    real, executed call appears -- not full JS lexing): a JSDoc `@example`
    block or an inline comment illustrating a call must not be mistaken for
    real code, and a comment mentioning a bogus field/doctype name must not
    turn a scan red. Does not attempt to handle a `//` inside a string literal
    (e.g. a URL) correctly; none of the files this is used on need that.
    """
    content = _BLOCK_COMMENT_PATTERN.sub("", content)
    return _LINE_COMMENT_PATTERN.sub("", content)
