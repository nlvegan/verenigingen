# 2026-09-10 — four bypasses, and a premise I had been handed in my own first message

**State at handoff:** `develop` at `83d53f77b`, green on all 7 workflows. **No open PRs.**
Two merged this session: **#1103** (the guest return-token / #1105 timing-oracle work,
inherited from the previous session) and **#1122** (a ratchet for #1112's vacuous
log-claiming test class). Issues filed: **#1120, #1123, #1124, #1125**, plus **#1121** by a
reviewer. Corrections posted to **#1112, #1123, #1124, #941**.

The session's work was small. The interesting part is that a gate built to catch tests that
cannot fail was itself defeated four times, and the issue I filed afterwards rested on a
premise that had been sitting in my own opening context.

---

## The through-line

**Every defect this session was a signal accepted for something it did not mean.** Not
missing evidence — evidence whose scope was narrower than the claim built on it. Same shape
as 2026-09-09's handoff, which is why it is worth stating that knowing the pattern did not
prevent it.

| what I accepted as "this test checks the log" | what defeated it |
|---|---|
| any string constant anywhere in the function | the test's own **docstring** — *"writes a security Error Log"* |
| any string constant in any **call's** arguments | an assertion **message**, `print(...)`, `logging.debug(f"...")`, a `@unittest.skip` argument |
| a literal in a read call, where "read" also matched `_ASSERTING_CALL` | **`expectErrorLog("Error Log")`** — the mute call's own argument, because that regex matches `expectErrorLog` and only one of two duplicated walks skipped it |
| the mute must be in the test BODY; a call that was merely **defined** counted | a class muting in `setUp` (16 files do this) was invisible; a never-invoked nested checker scored as sound |

Rounds 1–3 were each fixed by narrowing the *shape* the prose could hide in, which is
precisely why a fourth arrived. Round 3 deleted the duplicated walk that generated the
class; round 4 corrected a false premise. **Narrowing a shape does not close a class.**

---

## The one that cost the most: I contradicted an issue I had quoted an hour earlier

#1123 was filed with this as its central claim, and it is false:

> Without a mute, a test that triggers an Error Log write **fails** — the harness's
> automatic check catches it. So a log-claiming test with no mute is at most MISNAMED.

Two independent reasons, both verified:

1. `error_log_guard.py::_finalize_error_log_check` raises **only** when
   `fail_on_error_log_enabled()` is true, reading `VERENIGINGEN_FAIL_ON_ERROR_LOG`.
   Otherwise `print(f"WARNING: {summary}")`. The variable is set **nowhere** in `.github/`
   or `scripts/`. In the configuration CI runs, an undeclared Error Log write prints a line
   and the test **passes**.
2. `ErrorLogGuardMixin` arrives via `VereningingenTestCase`/`EnhancedTestCase`. Classes
   extending `FrappeTestCase`/`TestCase` directly get no check at all. **The gap is
   established; its size is not.** The review, resolving inheritance chains, reported 35 of
   #1123's 324-test complement in such classes; my cruder direct-base-name count says 123
   (an overcount — a class extending a local base that itself extends
   `VereningingenTestCase` reads as unguarded to it). Nobody has reconciled the two.

Reason (1) is **#1118**, filed 2026-09-10, which says exactly this — and I listed #1118 to
the user in my first message of the session, as one of the open items. I then wrote its
negation into an issue *and* into `vacuous_error_log_test_validator.py`'s shipped docstring
as the justification for the gate's scope.

**The lesson is not "read the issues".** I had read it. It is that a premise inherited from
my own summary got the same unexamined trust as one I had verified — the handoff I wrote
became a source I stopped questioning. Anything carried forward from a summary is a claim,
not a finding.

Consequence, now filed as **#1125**: the gate has a real blind spot. A vacuous log-claiming
test that simply *omits* `expectErrorLog`, in a class that does not inherit the mixin, is
#1112's defect exactly, and #1122 cannot see it because it keys on a mute such a test never
needed.

---

## What shipped

- **#1103** merged (`fa440fcd6`) on explicit instruction — guest-reachable payment access,
  #1105's existence-timing oracle, the `per_ip` rate rule and its patch. Verified green
  first (49 checks, 12/12 shards). Only **#1053** auto-closed; **#1052, #1055, #1105 are
  still open** and nobody has checked whether they hold real remainder.
- **#1122** merged (`83d53f77b`) — `scripts/validation/vacuous_error_log_test_validator.py`,
  zero-tolerance and **baseline-free** (population 0, so a baseline would be #985 debt and
  inherit #1110's shrink gate). Pre-commit hook plus its own CI job. Five commits: the
  ratchet, then one per review round.
- **Three genuinely vacuous tests fixed**, each mutation-proven (deleting the production
  `frappe.log_error` reddens exactly the intended test, same command both runs):
  `test_unknown_named_frequency_logs_and_falls_back`,
  `test_log_blocked_members_summary_logs_and_clears`,
  `test_missing_import_document_is_logged_not_raised`.
- **Six false positives classified and pragma'd** with recorded reasons; an independent
  reviewer read all six and agreed with all six.
- **#1112's deferred item discharged** — already fixed by #1103's merge, confirmed by
  mutation rather than by reading.

---

## Corrections to my own work — read these before trusting anything above

1. **#1123's central premise is retracted** (above). The issue needs a rewrite, not a
   footnote: partition by guarded vs unguarded class.
2. **"269 tests need classification" was the wrong question**, and I published it as the
   headline. That predicate is right for #1122's gate and wrong for a population where
   nothing can silently pass. The residue was full of the log validators' **own** unit
   tests. The tractable subset is tests with **no assertion of any kind**.
3. **That subset is 25, not the 23 I published.** `test_log_injection_prevention` was
   excluded for a reason I stated and that was false (its name contains neither `logged_in`
   nor `login`), and `test_log_info_swallows_underlying_failure` was missed while its four
   siblings in the same file were listed — a class-not-instance miss **inside a correction
   whose whole point was that the first number was careless**.
4. **"Dominated by the log validators' own unit tests" is refuted** — 20 of 269, 7.4%,
   across 125 files with no dominant contributor. The observation that sent me looking was
   real; the word "dominated" was never measured.
5. **#1124's "at least 6 security tests" should read five.**
   `test_secure_factory.py::test_field_validator` is a module-level function in a file with
   no class, so Frappe's loader never collects it. It never runs.
6. **My "#490 and #1124 do not bound each other" was a hedge covering work I had not
   done.** Diffed: PR #913 touched 7 SEPA/payments files; #1124's 26 include zero SEPA
   files. **The intersection is empty**, which is a stronger and more useful statement.
7. **A test in my own suite was passing on an unparseable snippet.** `scan_file` swallows
   `SyntaxError` and returns no findings, so a snippet with broken indentation yields `[]`
   and an assertion expecting `[]` passes on garbage. That is #1112's defect, inside the
   suite written to prevent #1112. `_names()` now fails loudly if a snippet does not parse.

---

## Highest-value open items

- **#1121** (filed by a reviewer) — `log_error(message, title)` swapped where **both**
  arguments are bare variables: 12 sites across 9 files, including `safe_log_error` itself,
  whose signature is documented `(title, message)` while its body swaps them. Invisible to
  the existing validator's bare-Name carve-out **and** to #970's proposed widening. Biggest
  untouched item on the board.
- **#1125 / #1118** — the shipped docstring is trivially fixable; the scope widening behind
  it is not, and needs a measured false-positive rate first. #1118 is the cheaper half: if
  strict mode ran in CI, reason (1) disappears for every guarded class.
- **#1124** — 26 zero-assertion tests, five genuinely security/permission.
  `test_api_permissions` is **mutation-proven** unable to detect the control it names:
  bypassing the guard entirely (`insert(ignore_permissions=True)`) left 12/12 green.
- **#1123** — needs the partition rewrite; quote **25**, with caveats, never 269.
- **#1052 / #1055 / #1105** — open after #1103's merge; check for real remainder.
- **#1120** — one-line fix (invalid escape sequence, `SyntaxError` in a future Python).

---

## Traps worth knowing

- **A premise carried forward from your own handoff is still a claim.** The most expensive
  error here was trusting my own summary. Re-verify anything a summary asserts before
  building on it, exactly as you would an issue body.
- **`VERENIGINGEN_FAIL_ON_ERROR_LOG` is unset in CI, so the automatic Error-Log check only
  `print`s a warning** (#1118). "The harness catches undeclared writes" is false today for
  every test, and doubly false for the classes that never inherit `ErrorLogGuardMixin`.
- **`pre-commit run --all-files` ignores untracked files.** A planted control file passed
  clean until it was `git add`ed. A gate control that is not staged proves nothing.
- **`scan_file`-style validators swallow `SyntaxError`.** Any test that feeds generated
  source to one must assert the source parses, or a typo silently yields "no findings".
- **Equal totals are not equal behaviour.** Fixing the `setUp` blind spot left findings at
  0 both before and after; only *scope* moved, 44 → 52 name-claiming tests considered. If a
  change is supposed to widen coverage, measure the coverage, not the verdict.
- **A review of the commit that answers a review is the one that gets skipped.** Rounds 2, 3
  and 4 each found a defect in the commit that answered the previous round. The reviewed SHA
  and the branch HEAD are different things.
- Frappe's runner collects only `unittest.TestCase` subclasses, so a module-level
  `def test_*` in a class-less file never runs however convincing its name is.
- **A reviewer's figure is a claim too.** The review that refuted my premise reported "20
  test files call `expectErrorLog` from `setUp`". Three independent methods over the same
  tree give **16**, and I could not reproduce 20 by any scoping I tried (a crude grep for
  both strings anywhere in a file gives 130, which is the shape that inflates these). The
  refutation stands on its mechanism, not on that number — but the number was wrong, and I
  nearly copied it into this document.

---

## If you do one thing

**#1121.** It is the only item here touching production money paths, it was found by
someone else while reviewing something unrelated, and it is invisible to both the gate that
exists and the widening already proposed for it. Everything else on this list is test-side.
