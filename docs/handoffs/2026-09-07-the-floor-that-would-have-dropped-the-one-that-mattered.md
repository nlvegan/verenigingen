# Handoff — 2026-09-07: the floor that would have dropped the one that mattered

Continues `2026-09-06b-the-exit-code-said-zero.md` (PR #986, still open).

Two merges, eight open PRs, thirteen issues filed. The useful content is not the
throughput — it is that a fix I proposed and got approved would have removed the
gate from the exact defect the same session had spent the morning establishing,
and only measuring caught it.

---

## The one that nearly shipped

#1000 fixes a real undercount: the duplicate-helper census counted *files*, so
four copies of a helper on four classes in one file counted as one. Correct, and
verified — `_persist_eur_company` now reports 20, and `grep -c` says 20.

Its side effect is that the blocking gate goes **220 → 260 families**. Review
sampled 16 of the 40 and found a real share were one-line delegators (`_run`: ten
copies of `return self.v._validate_rule(...)`) and Strategy-pattern overrides
(`_calculate_delay` × 4, all already delegating to a shared
`calculate_backoff_delay()`). I proposed a size floor: skip near-pair scoring for
bodies under N statements. The principle sounded right — *a body too short to
hide a divergence*. It was approved.

Measured before implementing, it drops **72 families**, and one of them is
`_sanitize_error_message`.

That is the family this same session had already investigated: five copies, all
**one statement**, and the divergence is entirely in the argument list — two pass
`filter_sensitive_keywords=True`, two silently take the `False` default and never
filter API keys or database details out of an error message. A one-line body can
absolutely hide a divergence. My stated principle was false, and the
counter-example was work I had done myself hours earlier.

What shipped instead skips a pair only when **both** bodies are under 3
statements **and** both definitions are in the **same file**:

| rule | families dropped | `_sanitize_error_message` |
|---|---|---|
| size-only floor | 72 | **dropped from the gate** |
| size **and** same-file | 8 | **kept** |

260 → 252. Both halves pinned by separate mutation tests: removing the exclusion
reddens the same-file test; removing only the same-file half reddens the
cross-file test.

**The transferable part:** the sentence "this heuristic is obviously safe" is a
measurement request, not a conclusion. The cost of checking was ten minutes. The
cost of not checking was silently un-gating a security-relevant divergence while
believing the opposite.

Still unaddressed and now the whole content of #1009: `_calculate_delay`'s
overrides are 5 statements, not trivial by size, and "these differ only by a
strategy argument and the real logic is already shared" is a semantic judgement
no size heuristic can make.

---

## Three false sentences in committed code, in one day

Not PR bodies — committed code, where the next reader treats them as established
fact and does not re-derive them.

1. **#1005's ratchet docstring**: *"Before this fix: 1. After: 0."* Mutation shows
   the test passes **identically** with the fix disabled, because the case it
   names is a singleton and singletons are excluded from that bucket. The real
   measurement came from an unshipped script. Corrected in `718242ecf`.
2. **#1006's module docstring**: cited the census as "745 duplicated names / 1531
   redundant copies" and "25 families". Running the committed scanner prints
   611 / 1341 / 17. Corrected in `2b6710535`.
3. **#988's test docstring**: cited "the live site has one of each family" as
   evidence docstatus 1/2 Donations exist in the wild. Those rows are on veg11 —
   a test instance — and are test remnants (`Test Donor`, `@example.com`,
   inserted and re-stamped 25 ms apart). Removed by #1007.

The previous handoff's title case was a false sentence I had written into a code
comment. It recurred three more times the next day, from three different authors.

---

## veg11 was cited as production data. Twice. One of them was me.

The project memory is explicit: veg11 is a test instance, never cite its row
counts as production figures. In this session:

* **I did it** — presented three non-zero-docstatus Donations as evidence
  cancelled donations "exist in the wild". Foppe asked how old they were. They
  are test remnants. The *code fact* (Frappe does not guard `_cancel()` on a
  non-submittable doctype) survives and is what should have been argued from.
* **A reviewer did it** — reported #1004's over-reporting as "1065 of 1660 (64%)
  … measured against a production data copy". The defect is real, established
  from the schema (`membership` is `reqd=0`) and the SQL alone. The magnitude is
  unknowable from this bench.

CLAUDE.md calls veg11 "a test site carrying a copy of production data". That
phrasing is what baits this. The memory note predicts exactly this failure and it
still happened twice in one session.

**When I re-measured the same defect on a test site and said so, the number was
better evidence *and* honest: 1589 schedules, essentially all `is_template = 1`.**

---

## Auto-merge merged with two test shards that never ran

I enabled auto-merge on #994 expecting it to wait for CI. It waits for *required*
checks. `Tests / Tests (1/12)` and `(4/12)` were not required; the PR merged
twelve seconds later and those two shards never started — not "finished late",
never ran. They were first exercised by develop's own push run afterwards, where
they passed.

"Merge when green" and "merge when required checks are green" are different
promises. The repo's branch protection decides which one you get.

---

## What I got wrong

* **The size floor** — above. Approved, then refuted by my own earlier work.
* **veg11 as production** — above.
* **`git checkout -- <file>` on uncommitted work.** Mutation-testing #1000, I
  reverted a mutation with `git checkout` and destroyed the *implementation*,
  which was not committed. The next mutation then ran against un-implemented code
  and produced a result I nearly reported. Mutation-test on a **copy**.
* **"More than was authorized."** I flagged an agent for removing a second
  production `.submit()` as scope creep. #987's body names that exact test at
  line 39. The agent was in scope; my brief was narrower than the issue.
* **`donation.company` as evidence of divergence.** I cited one fixture setting
  `company` and another not, as proof the two disagreed. **Donation has no
  `company` field** — 58 fields, none named company. Both were writing a phantom.
  That became #1012 (102 write sites, and a documented resolver that reads it).

---

## Reviews: five dispatched, five found something — and three corrected the reviewer

* **#1004** — request changes. Fixing a dead `docstatus = 1` predicate *unmasked*
  a second defect in the same query, turning "reports nothing" into "reports
  nearly everything". Fixed in `5e96419fc`.
* **#1000** — approve on correctness, but quantified the policy change riding
  along with it. 23 of the 40 newly-blocking families are entirely single-file.
* **#1005** — the false docstring above, found by mutating the thing the test
  claimed to demonstrate.
* **#1006** — three defects: a report that truncates away the evidence for its own
  finding, stale figures, and a hook CI never invokes (#1008).
* **#1007** — approve, and applied this repo's own "grep the explanation" rule to
  the PR that was following it: `ignore_validate` at 25 donation/donor sites,
  only two of which it asked about (#1011).

Reviewer premises corrected: veg11-as-production (#1004); `_ensure_mode_of_payment`
called a singleton when it has **six** copies (#1010).

**And one "correction" of mine that was itself wrong.** I told a reviewer its
claim of two live RQ workers was false — `pgrep -af "bench" | head -5` showed
only gunicorn and socketio. There are **15** matching processes; the workers are
at positions 14 and 15. `ps -eo pid,args` confirms
`frappe worker --queue short,default` and `--queue long,default,short` running,
plus the scheduler. The reviewer was right, my instrument was truncated, and I
reported the truncation as a finding. This is the `--limit 100` lesson from the
project memory — *a truncating fetch reads exactly like "nothing found"* — which
I had cited earlier the same day. Corrected on #1003.

That matters beyond the embarrassment: with workers actually running, the chain
in #1003 (a Donation insert enqueues a real job, `is_async=True` so it does not
run in-process even under `frappe.in_test`, and a worker is there to consume it)
is **established**, not refuted.

---

## The live defect

`notify_about_orphaned_records` is in the **daily** scheduler block
(`hooks/scheduler.py:31`). Its dues-schedule half filtered `mds.docstatus = 1` on
a doctype with `is_submittable = 0`, so it matched nothing, every day, since it
was written. Staff have never been alerted to an orphaned dues schedule. #350's
damage class, in a scheduled job rather than a report.

Its fix then had to be fixed: see #1004 above.

---

## Issues filed

**From the work:** #987, #988, #989 (submittability drift, donation fixtures,
shared-fixture landmine), #990 (census counts files), #991 (nothing scans
production for divergence), #992 (four more drift instances).

**From reviews:** #1008 (scanner hides its own evidence), #1009 (the gate blocks
trivial helpers), #1010 (six undecorated shared fixtures, invisible three ways
over), #1011 (25 `ignore_validate` sites), #1012 (phantom `company` field),
#1013 (`baseline_shrink_gate` reports a false PASS when run without the separate
`--update-baseline` step CI runs first — hit independently by two people).

**From agents:** #1001 (the shared factory force-writes `docstatus=1` with a raw
`db.set_value` to satisfy the very predicates #350 established are wrong — ~100
call sites), #1002, #1003.

---

## Merged

* **#922** — 28 harness-method-shadow instances plus a guard (#496).
* **#960** — Mollie permanent-refusal reason strings.
* **#993** — shared-fixture guard extended to module-level helpers (#989).
* **#994** — submittability drift on Donation/SEPA Mandate, plus a validator (#987).

---

## Open decisions — not mine

1. **Merge order is constrained**: #998 (baseline resync, clears a develop red
   that has stood since `ec047d04a`) must land before #1000, which stacks on it.
2. **#1000 still widens the gate** 220 → 252 even after the floor. That is mostly
   legitimate — real same-file clones like `_get_or_create_parent_account`, ~15
   lines byte-identical across five sibling classes — but ~24 of the 40 newly
   blocking families have not been read by anyone.
3. **#1006 ships an advisory check nothing invokes.** `stages: [manual]`, zero
   references in `.github/workflows/`. Advisory is right for 17 untriaged
   families; unreachable is not. #1008.
4. **veg11 has not been restarted.** The working tree is synced to `1ed3411a9`,
   but gunicorn runs `--preload`, so the live site is still executing the old
   code.

---

## Verified state

* `develop` at `1ed3411a9`; local checkout synced, clean.
* Server Tests **green, 14/14**, including the two shards #994's auto-merge
  skipped.
* Code Validation **red** on develop — the Duplicate Helper shrink gate, four
  pushes running. #998 fixes it. Both new validators (harness-method-shadow,
  submittability-drift) pass on the merged tree.
* Eight PRs open: #997, #998, #999, #1000, #1004, #1005, #1006, #1007 — plus #986
  (the previous handoff) and three predating this session (#980, #974, #896).
