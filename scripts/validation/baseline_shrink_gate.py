#!/usr/bin/env python3
"""Shared "does the regenerated baseline match the tree" gate for CI.

THE BUG THIS REPLACES
----------------------
Every ratchet in this directory pairs a validator with a checked-in
``*_baseline.txt``. The CI job for each one used to run the validator with
``--update-baseline`` and then ``git diff --quiet`` the result against the
committed file, failing on ANY difference with a generic "Baseline is out of
sync with the tree" message.

That message is correct when the census GREW (a new site, or a higher count
for one already listed) -- something needs fixing or the growth needs
reviewing. It is actively misleading when the census only SHRANK: shrinkage
means a baselined site was deleted or fixed, which is the entire point of a
ratchet, yet the message reads like a regression and sends the reader
hunting for one. Measured on ``develop`` at ``34fb9d5f2``: two sites deleted
by unrelated PRs (#719, #730) left the log_error_arg_order baseline stale,
and "every branch cut from that trunk inherited the failure" until someone
manually ran ``--update-baseline`` (#750) -- on a leap-day date fix that
touches no logging at all.

WHAT THIS SCRIPT DOES INSTEAD
------------------------------
Given the path to a baseline file that the caller has ALREADY regenerated on
disk (by running ``<validator> --update-baseline`` before invoking this),
compare it against ``git show HEAD:<path>`` -- the committed version -- and
classify every changed key:

* a key that is NEW, or whose count went UP, is growth -> still a hard
  failure, with the same actionable message as before (plus which keys).
* every other change is a key's count going down or the key disappearing
  entirely -- pure shrinkage, the good direction -- and self-heals: this
  step passes even though the committed file is now stale relative to the
  tree.

THE COST OF SELF-HEALING, AND WHY ``--fail-on-shrink`` EXISTS
------------------------------------------------------------------------
Self-healing is NOT free -- an earlier version of this docstring claimed it
was, wrong, per a skeptical review of the change that introduced this file.
Each validator's own "Ratchet check (whole tree)" step compares the TREE
against the COMMITTED baseline, not the regenerated one. Before this gate
existed, that committed baseline was FORCED to tighten every time a site was
fixed: CI failed on the stale file until someone ran ``--update-baseline``
and committed the smaller result, which is exactly what closed the "removed
slot can be silently refilled later" hole the comment beside every ratchet
job warns about. Unconditional self-healing removes that forcing function: a
site fixed today, with no regenerated baseline ever committed, leaves the
OLD (larger) count sitting in the repo indefinitely, and a key reintroduced
later at or below that stale ceiling is invisible to the whole-tree check.

``--fail-on-shrink`` closes most of that gap by putting the two ratchet
behaviours (self-heal / fail-with-the-exact-entries) on two different CI
triggers instead of picking one for both:

* On a ``pull_request`` run, self-heal (flag OFF). ``actions/checkout``
  checks out GitHub's auto-generated test-merge commit -- the PR head merged
  into the base branch's CURRENT tip -- so by the time an unrelated PR like
  #740 (a leap-day date fix, the one that actually surfaced this bug) runs,
  its checkout already contains whatever an earlier merged PR deleted. There
  is no PR-side failure to avoid reintroducing.
* On a ``push`` run (i.e. develop, right after a merge), fail (flag ON).
  Nothing downstream is blocked by that failure -- it is a report on a
  commit that already landed, not a gate in front of one -- so this is where
  the forcing function belongs: whoever merged the PR that shrank the
  baseline without regenerating it sees a red push and knows exactly what to
  fix, immediately, rather than three PRs later.

An earlier version of this section argued self-heal-only-on-`pull_request`
"brings back exactly the push-to-develop failure this file exists to
remove." That was wrong, caught by a second skeptical review: the actual
incident's damage was downstream PRs inheriting staleness through the
auto-merge checkout, which PR-side self-healing removes completely: the
push-side failure that remains is confined to the one commit that
introduced the staleness, blocks nothing else, and is worth keeping as the
tightening signal. See ``code-validation.yml`` for how the flag is threaded
through on ``github.event_name``.

This does not close the gap for `test_quality_enforcer.py` /
`duplicate_helper_validator.py`'s escape-hatch abuse case below -- a
suppression pragma added alongside a real fix still self-heals silently on
`pull_request`, same as before -- nor does it change anything about a
directly-pushed commit outside a PR at all (there is no "pull_request"
checkout to have already absorbed prior shrinkage in that case, so it always
takes the `--fail-on-shrink` path here too; this repo's history is exclusively
merge commits, so that path is untested in practice, not merely unlikely).

THE ONE CASE THAT MUST NOT SELF-HEAL
--------------------------------------
A regenerated census that comes back completely EMPTY while the committed
baseline is not is refused rather than self-healed, even though "empty" is
technically a subset of anything. This project has already hit exactly that
failure shape once: a validator unable to resolve its authority from a
worktree outside the bench loaded zero doctypes and printed "No issues
found" (see ``bench_resolution.py``'s docstring). A whole-tree baseline of
hundreds of sites reaching zero in one change is far more likely a scan that
silently found nothing than a single PR fixing everything, so this is the
one shrink shape that still fails, asking a human to confirm the scan
actually ran before trusting it.

A related failure shape: every line in one or both baselines fails to parse
at all (a format change, or a completely different file wired in by
mistake). Left unchecked this would make `old`/`new` look identical --
`classify()` would see no changed keys and get self-healed regardless of
whether the tree actually grew -- so `main()` refuses to proceed unless it
can account for every non-comment, non-blank line on both sides.

SCOPING TO A SUBSET OF LINES (``--require-marker``)
------------------------------------------------------
``duplicate_helper_validator.py``'s baseline records TWO kinds of entry: a
name marked ``# clone family`` (near-identical copies -- what the ratchet
actually blocks on) and an unmarked name collision (same name, unrelated
bodies -- reported, never blocked; see that validator's own module
docstring). Comparing the WHOLE file, as every other caller of this gate
does, cannot tell those apart: an unmarked count going up looks exactly like
a marked one going up, so this step failed on it regardless -- issue #769,
where two test-double builders happened to share a name with six and two
unrelated helpers, and the validator's own ``--report`` called the shared
name "very likely a coincidence rather than a copy-paste". The only way to
turn this step green was to rename the new helpers, teaching contributors
that private test-helper names are effectively global, which is exactly the
"only exit is renaming" the validator was written to stop imposing.

``--require-marker TEXT`` fixes that by restricting BOTH sides to data lines
containing ``TEXT`` before anything else runs -- including the fast-path
equality check, so an unmarked-only change never even reaches ``classify()``.
A marked entry's count still changing is unaffected: it is still a hard
failure (or self-heals on pure shrinkage, per the flag above), because that
is the one class of growth this ratchet exists to catch. The other three
callers of this gate have no such split in their baselines and pass nothing
for this flag, so their behaviour is unchanged.

The filtering happens BEFORE the parse-coverage guard too (see "A related
failure shape" above), which is why that guard stays correct rather than
misleading once scoped: it re-runs ``data_lines()`` on text that has already
been reduced to marked lines, so every line it sees was already known to
parse (the marker is stripped during parsing, not during this filter) --
an unmarked line failing to parse is out of scope by design and cannot hide
behind this flag, because a MARKED line's format changing (gaining or losing
the marker) is still caught, either by keeping the marker and tripping this
guard, or by losing it and falling into "the regenerated census is EMPTY"
below.

The filter is keyed on a bare substring, not a parsed field, and this gate
cannot import ``duplicate_helper_validator.CLONE_MARK`` to stay in sync with
it (one caller is a shell grep, the other a subprocess argument) -- see the
zero-matched-lines refusal in ``main()`` for what happens if that string
drifts out of sync with what the validator actually writes, and
``test_duplicate_helper_validator.py``'s ``MarkerLiteralTest`` for where the
literal is pinned at its source instead.

WHAT THIS DOES NOT COVER
--------------------------
Whether a shrink was a GENUINE fix, as opposed to a suppression pragma
tacked onto an existing site or the site's file leaving the scanned roots,
is a validator-specific question. ``error_swallow_validator.py`` and
``log_error_arg_order_validator.py`` answer PART of it with their own
``--check-shrink``/``explain_shrink`` (run separately, PR-only, in
``code-validation.yml``) -- but that only reports a pragma added on top of
an EXISTING baselined site; it says nothing about a pragma added at the same
time a site is otherwise legitimately fixed, and this gate's self-heal does
not distinguish that case either. ``test_quality_enforcer.py`` and
``duplicate_helper_validator.py`` have no such check at all: the former's
own unpoliced `# Mock justified:` / `# External service` / `# Infrastructure`
escape hatches (see its baseline header) can make an existing violation
vanish from the census without the underlying test being fixed, and
self-healing here means that no longer shows up as a reviewable diff. This
is a real, currently-accepted gap in exactly those two ratchets, widened (not
merely inherited) by wiring this gate in without a compensating check for
them; see the commit that introduced this file for the tradeoff.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def data_lines(text: str) -> list[str]:
    """Non-blank, non-comment lines -- the ones `parse_baseline` should account for."""
    return [line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


def _parse_line(line: str) -> tuple[str, int] | None:
    """Parse one already-known-non-blank, non-comment baseline line.

    Every baseline in this directory keys on everything before the LAST
    ``::`` and a count after it. The inline ``  # clone family, ...`` marker
    ``duplicate_helper_baseline.txt`` can carry is stripped BEFORE splitting
    on ``::`` -- exactly what ``duplicate_helper_validator.load_baseline``
    does, and NOT just tolerated via a leading-digits match on the tail,
    which would let a marker containing its own ``::`` get swallowed into
    the key. The other three wired baselines (error_swallow,
    log_error_arg_order, test_quality) do not strip ``#`` in their own
    ``load_baseline``, so this gate is deliberately STRICTER than those
    three: a literal ``#`` inside a path or qualname there would fail to
    parse here (and be caught, loudly, by the coverage check below) rather
    than silently misparse. No such line exists in any of the four baselines
    today.

    Returns None for a line that does not fit the shape at all, which is
    also how `parse_baseline`'s caller checks parse COVERAGE -- see
    "THE ONE CASE THAT MUST NOT SELF-HEAL".
    """
    line = line.split("#", 1)[0].strip()
    if not line:
        return None
    key, sep, rest = line.rpartition("::")
    if not sep:
        return None
    rest = rest.strip()
    if not rest.isdigit():
        return None
    return key, int(rest)


def parse_baseline(text: str) -> dict[str, int]:
    """Map ``key -> count`` from a ``<key>::<count>[  # trailing note]`` file."""
    out: dict[str, int] = {}
    for line in data_lines(text):
        parsed = _parse_line(line)
        if parsed is None:
            continue
        key, count = parsed
        out[key] = out.get(key, 0) + count
    return out


def committed_content(path: Path) -> str | None:
    """``HEAD``'s copy of `path`, or None if the file is simply new at HEAD.

    The working tree copy has already been overwritten by the caller's
    ``--update-baseline`` run by the time this is invoked; ``HEAD`` still
    points at the same commit either way, so this reads the pre-regeneration
    content without needing a stash.

    ``git show HEAD:<path>`` resolves `path` relative to the repo's top
    level, not the current directory, so an absolute (or cwd-relative) path
    is first translated via ``git rev-parse --show-toplevel``. That first
    step failing means something more fundamental than "file is new" (not a
    git repo at all, HEAD unborn, ...), so it is treated as a hard error
    rather than silently waved through as "nothing to check" -- only a
    genuinely missing blob at an otherwise-resolvable HEAD is.
    """
    resolved = path.resolve()
    toplevel = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=resolved.parent,
        capture_output=True,
        text=True,
    )
    if toplevel.returncode != 0:
        raise RuntimeError(
            f"git rev-parse --show-toplevel failed in {resolved.parent}: {toplevel.stderr.strip()}"
        )
    rel = resolved.relative_to(Path(toplevel.stdout.strip()).resolve())
    result = subprocess.run(
        ["git", "show", f"HEAD:{rel.as_posix()}"],
        cwd=resolved.parent,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def classify(old: dict[str, int], new: dict[str, int]):
    """Split changed keys into (grown, appeared, shrunk).

    ``grown``: key present in both, count went up -- ``{key: (old, new)}``.
    ``appeared``: key present only in `new` -- ``{key: count}``.
    ``shrunk``: key whose count in `new` is lower than in `old`, including a
    key missing from `new` entirely (count 0) -- ``{key: (old, new)}``.
    """
    grown = {k: (old.get(k, 0), v) for k, v in new.items() if k in old and v > old[k]}
    appeared = {k: v for k, v in new.items() if k not in old}
    shrunk = {k: (old[k], new.get(k, 0)) for k in old if new.get(k, 0) < old[k]}
    return grown, appeared, shrunk


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("baseline", type=Path, help="baseline file, already regenerated on disk")
    ap.add_argument(
        "regenerate_cmd",
        help="the command to print for tightening/regenerating this baseline",
    )
    ap.add_argument(
        "--fail-on-shrink",
        action="store_true",
        help=(
            "Fail (with the exact entries and command, not the generic "
            "message) instead of self-healing on pure shrinkage. Intended for "
            "a `push` CI run, where nothing downstream is blocked by the "
            "failure and it is the only remaining forcing function that "
            "tightens the committed baseline -- see 'THE COST OF "
            "SELF-HEALING' above."
        ),
    )
    ap.add_argument(
        "--require-marker",
        default=None,
        help=(
            "Scope the whole comparison to data lines containing this substring "
            "(e.g. duplicate_helper_baseline.txt's '# clone family' marker) -- a "
            "line missing it never counts as grown, appeared, or shrunk, on "
            "EITHER side. See 'SCOPING TO A SUBSET OF LINES' above: without this, "
            "a baseline that also records non-blocking entries (a name collision "
            "the validator itself reports as advisory) forces a sync commit for "
            "those too, which is where issue #769 came from."
        ),
    )
    args = ap.parse_args(argv[1:])

    new_text = args.baseline.read_text(encoding="utf-8") if args.baseline.exists() else ""
    try:
        old_text = committed_content(args.baseline)
    except RuntimeError as exc:
        print(f"::error file={args.baseline}::Could not resolve the git repository for this baseline: {exc}")
        return 1
    if old_text is None:
        print(f"No committed copy of {args.baseline} to compare against -- nothing to check.")
        return 0

    scope_note = ""
    if args.require_marker:
        # Filter BEFORE any comparison, including the fast-path equality check
        # below, so a change confined to non-matching lines (e.g. a growing
        # advisory-only count) is invisible to every later step -- not just
        # reclassified once it reaches `classify()`. That matters for the
        # "text differs but no key changed" fallback near the end of this
        # function: without filtering up front, an advisory-only change would
        # reach that branch (still "text differs") and fail there instead,
        # under a more confusing message, defeating the whole point.
        old_lines = data_lines(old_text)
        new_lines = data_lines(new_text)
        old_marked = "\n".join(line for line in old_lines if args.require_marker in line)
        new_marked = "\n".join(line for line in new_lines if args.require_marker in line)

        # A skeptical review of this change caught the shape "THE ONE CASE
        # THAT MUST NOT SELF-HEAL" was written for, wearing a different hat:
        # if the marker string itself drifts out of sync with what the
        # validator actually writes (CLONE_MARK renamed here without the
        # hardcoded --require-marker literal in code-validation.yml being
        # updated to match), filtering finds NOTHING on either side, the
        # fast-path equality check below sees "" == "" and reports a clean
        # match -- even though real, unfiltered growth exists in the file
        # that this run was supposed to be scoped to. That is a scan that
        # silently found nothing, not a genuine zero-clone-family census, and
        # must be refused rather than trusted, exactly like the whole-census
        # empty case below. A baseline with no data lines AT ALL on either
        # side is unaffected -- there is genuinely nothing to check.
        if not old_marked and not new_marked and (old_lines or new_lines):
            print(
                f"::error file={args.baseline}::--require-marker {args.require_marker!r} "
                f"matched no line in the committed baseline ({len(old_lines)} data line(s)) "
                f"or the regenerated one ({len(new_lines)} data line(s))."
            )
            print(
                "That is far more likely a stale marker string (renamed in the validator "
                "that writes this baseline, not updated in the caller of this gate) than "
                "every marked entry disappearing in the same change. Confirm the marker "
                "still matches what the validator actually writes, then regenerate by hand "
                "if it checks out:"
            )
            print(f"    {args.regenerate_cmd}")
            return 1

        old_text, new_text = old_marked, new_marked
        scope_note = f" (lines containing {args.require_marker!r} only)"

    if old_text == new_text:
        print(f"{args.baseline}: matches the tree{scope_note}.")
        return 0

    old = parse_baseline(old_text)
    new = parse_baseline(new_text)

    # A key defence against a silent false-pass: if either side's parse
    # accounted for fewer lines than it actually has, `old`/`new` describe an
    # UNKNOWN fraction of the real file -- possibly one that hides growth --
    # so this refuses to classify at all rather than risk self-healing a
    # regression it could not see. See "THE ONE CASE THAT MUST NOT SELF-HEAL".
    for label, text in (("committed", old_text), ("regenerated", new_text)):
        lines = data_lines(text)
        covered = sum(1 for line in lines if _parse_line(line) is not None)
        if covered != len(lines):
            print(
                f"::error file={args.baseline}::Cannot parse the {label} baseline: "
                f"only {covered} of {len(lines)} non-comment lines matched "
                f"'<key>::<count>'. The format may have changed -- refusing to guess "
                f"whether this is growth or shrinkage."
            )
            return 1

    grown, appeared, shrunk = classify(old, new)

    if grown or appeared:
        print(f"::error file={args.baseline}::Baseline is out of sync with the tree.")
        print("Regenerate it and commit the result:")
        print(f"    {args.regenerate_cmd}")
        if appeared:
            print("\nNew entries:")
            for k, v in sorted(appeared.items()):
                print(f"  + {k}::{v}")
        if grown:
            print("\nEntries whose count increased:")
            for k, (before, after) in sorted(grown.items()):
                print(f"  ~ {k}::{before} -> {k}::{after}")
        if shrunk:
            # Growth and shrinkage can land in the same change (three sites fixed,
            # one added) -- surface the shrunk side too so the reviewer does not
            # have to re-derive it from the diff by hand.
            print("\nEntries that also left the baseline (fine on their own):")
            for k, (before, after) in sorted(shrunk.items()):
                change = "removed entirely" if after == 0 else f"{before} -> {after}"
                print(f"  - {k}  ({change})")
        return 1

    if old and not new:
        print(f"::error file={args.baseline}::The regenerated census is EMPTY, but the committed baseline has {len(old)} entries.")
        print(
            "That is far more likely a scan that silently found nothing (wrong scan "
            "roots, an unresolved authority, an empty checkout) than every one of "
            "those sites being fixed in a single change. Confirm the validator "
            "actually scanned real files, then regenerate by hand if it checks out:"
        )
        print(f"    {args.regenerate_cmd}")
        return 1

    if not shrunk:
        # The text differs but no key counted as grown, appeared, or shrunk --
        # e.g. a header/comment edit, a trailing-annotation change (duplicate_
        # helper's recomputed clone-share percentage), or line reordering.
        # That is not shrinkage, so it gets none of the self-heal reasoning
        # above: fail and say so plainly rather than print an empty "entries
        # that left the baseline" list and pass.
        print(f"::error file={args.baseline}::Baseline text changed, but no key's count went up, down, or disappeared.")
        print(
            "Likely a header/comment/formatting change (or, for duplicate_helper, a "
            "recomputed clone-share percentage with no count change). Review the diff "
            "by hand and regenerate if it checks out:"
        )
        print(f"    {args.regenerate_cmd}")
        return 1

    # Every changed key only shrank or disappeared -- the good direction.
    if args.fail_on_shrink:
        # Deliberately still a failure: on a `push` run there is no PR to
        # inherit a misleading message, and nothing else forces the committed
        # baseline to ever tighten (see "THE COST OF SELF-HEALING"). Same
        # entries as the self-heal branch below, but option (b)'s shape: name
        # exactly what left and the exact command, then fail.
        print(f"::error file={args.baseline}::Baseline census shrank -- tighten the committed file to match.")
        print("Entries that left the baseline (the good direction -- this is not a regression):")
        for k, (before, after) in sorted(shrunk.items()):
            change = "removed entirely" if after == 0 else f"{before} -> {after}"
            print(f"  - {k}  ({change})")
        print(f"\nRegenerate and commit:\n    {args.regenerate_cmd}")
        return 1

    # Self-heal: this is not a regression, so it does not fail the build.
    print(f"{args.baseline}: the committed baseline is stale, but only in the good direction -- self-healing.")
    print("Entries that left the baseline:")
    for k, (before, after) in sorted(shrunk.items()):
        change = "removed entirely" if after == 0 else f"{before} -> {after}"
        print(f"  - {k}  ({change})")
    print(f"\nOptional: tighten the committed baseline to match by running:\n    {args.regenerate_cmd}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
