#!/usr/bin/env python3
"""Render one chaos shard's result as Markdown for the job summary.

Reads the JSON `order_dependence_detector.py --json-out` writes and prints a short
report. Called by `.github/workflows/chaos-shards.yml`.

A script rather than shell-with-embedded-python in the workflow, for two reasons: an
embedded version cannot be tested, and a summary that silently renders nothing looks
exactly like a run that found nothing -- which is the confusion the chaos job exists to
remove. So a clean shard says so out loud, and a missing result file says THAT out loud
rather than raising.

Usage:  summarise_chaos_result.py <chaos_result_N.json>
"""

import json
import sys
from pathlib import Path

# A whole shard can fail at once (one poisoned fixture in setUpClass), and 300 bullets
# would bury the summary. The remainder is stated rather than dropped -- see the
# no-silent-caps rule: a truncated list that does not say it was truncated reads as
# complete.
MAX_LISTED = 40


def render(data: dict) -> str:
    """Markdown for one shard's result."""
    bad = list(data.get("failures") or []) + list(data.get("errors") or [])
    lines = [
        f"Ran {data.get('tests_run', '?')} tests, "
        f"{data.get('n_failures', '?')} failures, {data.get('n_errors', '?')} errors."
    ]

    if not bad:
        lines.append("")
        lines.append("No failures under this layout.")
        return "\n".join(lines)

    lines.append("")
    lines.append("Failing under this layout:")
    lines.append("")
    for item in bad[:MAX_LISTED]:
        lines.append(f"- `{item}`")
    if len(bad) > MAX_LISTED:
        lines.append("")
        lines.append(f"...and {len(bad) - MAX_LISTED} more (see the artifact).")
    return "\n".join(lines)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: summarise_chaos_result.py <chaos_result_N.json>", file=sys.stderr)
        return 2

    path = Path(argv[0])
    if not path.exists():
        print("The shard did not finish — no result JSON was written. See the job log.")
        return 0

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        print(f"The result JSON is unreadable ({error}). See the job log.")
        return 0

    print(render(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
