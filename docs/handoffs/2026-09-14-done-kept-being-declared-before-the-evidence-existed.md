# 2026-09-14 — "done" kept being declared before the evidence existed

**State at handoff:** `develop` at `757ea66f9`. **No open PRs.** Three merged this session:
**#1128** (the #1121 `log_error` bare-Name swap), **#1129** (#1118/#1125, the Error-Log
strict-mode decision), **#1136** (#1124's zero-assertion tests). Six issues closed —
**#1052, #1055, #1105** (already fixed, never closed), **#1118, #1120, #1121**. Nine filed:
**#1127, #1130, #1131, #1132, #1133, #1134, #1135, #1137, #1138**.

The previous handoff's "if you do one thing" was #1121. It is done. Everything else on its
list is either closed or still open with its remainder written down.

---

## The through-line

**Every blocking defect this session was found by CI, after someone had already said the
work was finished.** Four review passes ran — two agent self-reviews, two independent
skeptical reviews — and none of them caught either blocker. That is not a competence
problem: the analyses were good, and the skeptical reviews each independently re-derived
populations and re-ran mutations. The failure was always the same shape, and I committed it
myself twice:

| who | what they checked | why it settled nothing |
|---|---|---|
| #1128's reviewer | "All CI checks report `pass`" | the 12 test shards were still **queued**; two later failed |
| me, on #1136 | `pre-commit run --files <changed>` — all hooks passed | the failing gate was a `pull_request` **job**, which pre-commit does not run |
| #1128's author, round 2 | pushed a correct fix, reported done | the push introduced **two new** gate failures nobody looked for |
| me, in a shipped docstring | "697 tests, 0 flipped" | a **mid-run snapshot** of a job still running; the real number was 1,136 |

The fix is mechanical and I have adopted it: **`gh pr checks <n>` is the acceptance
criterion, run by me, after the run settles** — not a local hook run, not an agent's report,
not a reviewer's glance. I armed monitors instead of polling and stopped reporting anything
as ready until I had run it.

---

## The board was stale: three "open items" were already fixed

The previous handoff listed **#1052, #1055, #1105** as open with "nobody has checked whether
they hold real remainder". All three were fully fixed by #1103 and had simply never been
referenced by a closing keyword. Verifying that took about twenty minutes and it was the
single highest-return act of the session.

**I verified them against the running system, with controls, not by reading the diff:**

* **#1052** — Guest supplying a valid matching `(member, invoice)` pair → refused; the
  owning member's own session → allowed. The second line is the control; without it the
  refusal is equally consistent with "the page is broken for everyone".
* **#1055** — `payment_id` omitted and wrong token both refused; a **valid** token still
  returns the real document with its real amount, and a disallowed doctype still refuses
  with a valid token.
* **#1105** — re-ran the issue's own 300-call benchmark: **median ratio 10.30x → 1.00x**,
  both paths now ~4.5µs because neither reaches a DB round-trip. I reported the avg ratio
  (2.51x on a ~7µs absolute gap) rather than only the median that flatters the fix.

**Check the premise before dispatching.** `CLAUDE.md` already says this; it cost nothing
here and would have cost three wasted agent-hours.

---

## #1118: one buried decision produced four artifacts

The question #1118 asks — *should `VERENIGINGEN_FAIL_ON_ERROR_LOG` be enforced in CI?* — was
decided **deliberately on 2026-06-20**. The whole suite was run under the flag, sharded 6
ways: ~1,066 of ~11,000 tests flipped (~9.5%), overwhelmingly test artifacts in four
catalogued shapes. Conclusion recorded then: *"a one-time AUDIT tool, NOT a CI gate."* It
found seven real product bugs, which is what it is for.

That decision lived **only** in `docs/plans/2026-06-20-error-log-guard-and-fail-mode-audit-handoff.md`,
while `error_log_guard.py`'s own docstring still said the flag *"lets the rollout be
controlled (CI job, local run)"* — reading as **pending**. The cost:

* **#1118** re-asked the settled question,
* **#1123** built a false premise on it,
* **#1125** was filed about the consequence,
* **#1122** shipped a validator docstring asserting the opposite of reality.

**Four artifacts, one buried decision.** #1129 moved it into that module docstring with its
measured basis. **A decision recorded only in a handoff is not recorded** — put it in the
docstring of the thing it governs, because that is where the next reader lands. This
generalises far beyond this flag and is the cheapest fix available for repeated
re-litigation.

The failures are **concentrated, not uniform**, which matters for anyone re-running the
audit: 1,136 tests across 81 harness/ratchet/SEPA modules flipped **zero**, while
`test_mollie_reconciliation_engine` alone flipped **9 of 39 (23%)** and
`test_mollie_www_pages_coverage` **2 of 15**. Both wrong inferences are available from a
partial run.

---

## What CI caught that four reviews did not

### #1128 — a test that encoded the bug, then a `TypeError` on the error path

**Round 1** went red on shard 2: `test_safe_log_error_truncates` filters `Error Log` on
`method LIKE 'yyyyy%'`, and its own comment says the truncated message is *"passed as the
log title (`Error Log.method`)"*. **That is the defect #1128 fixed.** The production change
was right; the test asserted the swap. Making a red test green by editing the test is
legitimate here, and it carries `CLAUDE.md`'s extra burden — the evidence is the test's own
comment documenting the swapped placement as intended.

**Round 2** went red on shard 8, and this one is the genuinely valuable find. Frappe's own
swap heuristic (`frappe/utils/error.py:61-63`) is:

```python
if message:
    if "\n" in title:   # no None guard
```

Every `safe_log_error(message, title=None)` clone has callers that omit the title. The old
**swapped** call survived that: `None` landed in frappe's *message* slot and short-circuited
`if message:`. The keyword fix puts `None` in the *title* slot with a truthy message →
`TypeError: argument of type 'NoneType' is not a container or iterable` — **on error-logging
paths, i.e. exactly where something has already gone wrong.** All 5 clones fixed with a
first-line fallback; new regression test was RED for all 5 before the guard.

**This is the strongest argument on record for why the `log_error` arg-order class must not
be swept mechanically.** ~975 sites are still baselined. The naive fix introduces a crash on
the failure path.

**Round 3** went red on two gates the round-2 fix introduced: `controller-size-check`
(`volunteer.py` at 1,024 vs a 1,020 max — the explanatory comment pushed it over; the limit
counts **non-blank** lines, not `wc -l`) and the `Order-Dependence Ratchet` (the new
regression test added two bare `frappe.db.commit()` calls).

### #1136 — a test made green by working around a production bug

The `Order-Dependence Ratchet` was failing **on the PR** (it is a `pull_request` gate, not
push-only): `test_temporal_validation`'s two `frappe.db.commit()` calls took that file's
COMMIT count 4→6 with the baseline unregenerated. The self-review reported "the one
`frappe.db.commit()`" — there were two, and the miscount is how the rest went unnoticed.

The independent review then found the commits leaked a **Member row on every run (3/3)**:
the mid-test commit persists `setUp`'s fixtures while the cleanup only removed the Payment
Entry it created (**#1137**).

Both commits existed to dodge `_process_subscription_payment`'s `frappe.db.begin()` raising
`ImplicitCommitError` — a production defect the same agent filed as **#1134**. We reverted
the whole fix. **A test that is green because the harness commits around a real bug is worth
less than an honest gap**, so #1124 stays open for that one test and the PR shipped 11
fixes, not 12.

---

## Corrections to my own work — read these before trusting anything above

1. **I shipped two wrong numbers in a docstring.** "697 tests / 13 SEPA modules" was really
   **1,136 tests / 38 SEPA modules**. 697 was a mid-run snapshot I read while the job was
   still running and then wrote up as final. Corrected in `e7e1fbdd6` — but only because an
   independent review could not reproduce it, since **I never recorded the module list**.
   The 81-module list is now in #1118's thread.
2. **I did not disclose that run was stopped partway.** Frappe orders modules roughly
   alphabetically, so it never reached `tests.payment`/`financial`/`www` — precisely where
   the artifacts live. It is a partial run over an accidentally gateway-free slice, which is
   far weaker than "1,136 tests flipped zero" sounds.
3. **My first probe of #1131 was wrong and proved nothing.** `scan_file` returns a **tuple**,
   which is always truthy, so testing the return value for truthiness reported all six
   snippets as "flagged" — including the controls. Reading the findings list instead gave
   the real answer. *A probe whose control also passes is not a probe.*
4. **I reported "all gates pass" on #1136 from `pre-commit run --files`** while the gate that
   was actually failing was a `pull_request` job. Local hooks are not CI.
5. **I carried "at least 35 unguarded classes" into a shipped docstring without deriving it.**
   It is attributed as a floor with its provenance and the unreconciled 123, and I said so —
   but I did not reconcile it either, and nobody has.
6. **My push-only-gate simulation was itself broken, twice, and its first verdict was
   meaningless.** Writing the instrument is not the same as validating it:
   * I captured `rc=$?` **after piping the gate's output to `tail`**, so every `exit=` my
     harness printed was `tail`'s status, not the gate's. All eight read `exit=0` while one
     was actually failing. This exact trap is already in `CLAUDE.md`.
   * When I re-ran that one properly it exited **1** — and I nearly reported develop as
     broken. The control saved it: the identical failure reproduces on **pre-merge**
     `aac02e8a1`, so it was not mine. Then CI on that same SHA said `success`, which meant my
     command still did not match CI's: I had omitted **`--require-marker "# clone family"`**,
     which deliberately ignores unmarked name collisions. With CI's real flags the gate is
     **exit 0, "matches the tree"**.

   Net: all 8 gates pass on `757ea66f9`. But the first run said 8/8 pass for the wrong
   reason, the second said "develop is red" wrongly, and only the third was right. **A gate
   simulation must be copied from the workflow verbatim — flags included — and its exit code
   must not travel through a pipe.**

---

## Highest-value open items

- **#1130** — one failed Mollie call writes **three** Error Log rows through three
  log-and-propagate layers (`http_client.py:308` → `error_handler.py:202` →
  `mollie_subscription_audit.py:93`), and the most contextful one is argument-swapped and
  already baselined. Production log-volume, 3x amplification during an outage.
- **#1134** — `_process_subscription_payment`'s `frappe.db.begin()` raises
  `ImplicitCommitError` against any connection with prior writes. Possibly latent in
  production, and it currently blocks #1124's last test.
- **#1127** — both primary developer guides tell you to run the suite against **veg11**, the
  production-data-copy site: **9 commands across 2 files**, and neither guide mentions a test
  site anywhere. Same class as the closed #313, via the documentation vector.
- **#1131** — the new arg-order heuristic keys on the substring `"title"`: misses swaps named
  `subject`/`header`/`label`, and falsely flags a *correct* call whose message variable
  contains `"title"`. Both verified with controls; neither has a live instance today.
- **#1132** — nothing pins "the strict flag is absent from CI", so #1129's own load-bearing
  docstring claim can go silently false.
- **#1123 / #1125** — the expensive halves. #1123 needs the partition rewrite (quote **25**,
  never 269); #1125 needs the 35-vs-123 reconciliation *before* any widening, since the
  false-positive rate depends on which population you widen over.
- **#1137, #1133, #1135, #1138** — smaller, each with its boundary written down.

---

## Traps worth knowing

- **Copy a CI command verbatim when simulating it.** `duplicate_helper`'s gate carries
  `--require-marker "# clone family"`; without it the gate reports failures CI deliberately
  ignores. And never read an exit code through a pipe — `cmd | tail` gives you `tail`'s status.
- **`gh pr checks` is the only acceptance criterion.** Not a local `pre-commit` run, not an
  agent's report, not a reviewer's glance at a run that had not settled. Three of this
  session's rounds died here.
- **EIGHT `--fail-on-shrink` gates are push-only** —
  `FAIL_ON_SHRINK: ${{ github.event_name != 'pull_request' && '--fail-on-shrink' || '' }}` at
  `code-validation.yml:247, 363, 526, 634, 838, 927, 1015, 1103`, covering
  `submittability_drift`, `error_swallow`, `log_error_arg_order`, `db_clock_date_window`,
  `critical_operation_rule_orphan`, `test_quality`, `duplicate_helper` and
  `order_dependence`. A green PR says nothing about any of them. **Simulate before merging**:
  regenerate each baseline in a scratch worktree and run `baseline_shrink_gate.py …
  --already-regenerated --fail-on-shrink`.
  **I got this wrong first: I found three, simulated three, and wrote "three" into this
  document before grepping for the pattern.** `grep -n "FAIL_ON_SHRINK: "` returns eight. It
  is the class-not-instance rule, violated while writing the handoff that preaches it — and
  the two I had skipped (`test_quality`, `order_dependence`) are precisely the ones these
  merges were most likely to move.
- **The `Order-Dependence Ratchet` is NOT push-only** — it runs on `pull_request` and it
  gates bare `frappe.db.commit()` in test bodies. It exempts commits inside
  `_cleanup_*`/`_create_*`/`tearDown` helpers only.
- **`tabError Log` is MyISAM and `log_error` inserts in the current transaction**, so a
  same-connection read-back sees the row immediately. A commit to "make the row visible" is
  almost always unnecessary — and it trips the ratchet above.
- **`frappe.log_error(title=None, message=<truthy>)` raises `TypeError`** inside frappe's own
  swap heuristic. Any arg-order fix must guarantee a non-empty title.
- **`controller-size-check` counts non-blank lines**, not `wc -l`. A comment block can trip it.
- **`scan_file`-style validators return a tuple.** Truthiness-testing the return value makes
  every input look like a finding, controls included.
- **A reviewer will disclose its own mistakes — verify them anyway.** One removed a stranger's
  worktree while cleaning up and said so unprompted; I confirmed the branch still resolved
  with 0 commits ahead of develop, so nothing was lost. Trust the disclosure, check the claim.
- **Give every concurrent agent its own test site.** Four ran here on sites 2, 3, 6, 7, 8 with
  no contention.

---

## If you do one thing

**#1130.** It is the only open item touching a production path at volume, it was found in
passing rather than by anyone looking for it, and its third layer is an argument-swapped
`log_error` that is already baselined — so the row carrying the most business context is the
one recording no diagnostic content. Everything else on the list is test-side or documentation.

Second, if you have appetite for it: **#1134**, because it is a real production transaction
defect *and* it is what unblocks #1124's last test.
