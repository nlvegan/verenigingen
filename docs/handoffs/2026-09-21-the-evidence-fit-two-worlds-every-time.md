# 2026-09-21 — the evidence fit two worlds every time

Six PRs merged, one pending CI, one held as a draft on purpose, 31 issues filed.
Every fix that shipped was correct. **Almost every claim made *about* a fix was wrong at least once**, and in three
separate cases the wrongness had the same shape: evidence that confirmed the belief while
being equally consistent with its opposite.

That is the thing worth carrying out of this session. The rest is bookkeeping.

---

## The shape, three times

**1. I cited a commit subject as proof of intent.** Briefing an agent on #1224 I wrote that
the `Verenigingen Staff` `submit: 1` grant was deliberate "because `7c0271d38` is
*feat(sepa): add two-person approval workflow for batches*" — and I had actually run
`git log --oneline -1` and seen that subject, so I reported to the user that I had
"confirmed the intent trail."

That commit **changes no permissions.** It adds `approved_by` / `approved_on` and nothing
else. `git log --follow` shows the Staff grant predates it, arriving in the original
squashed import `2dbea04eb "fixes"`. The four-eyes service it added was later deleted as
dead (`2ea9e3209`) — it operated on `status` values that were never valid options.

A commit subject is the author's claim about a commit, exactly as an issue body is a claim
about a defect. The dispatched agent read the diff, found the premise false, and on that
basis **refused the fix my brief proposed** as an unestablished privilege expansion. That
refusal was right. **PR #1226's body repeated the same false premise**; it has since been
corrected in place — a `[!WARNING]` banner at the top of the body pointing to
[the re-measurement](https://github.com/nlvegan/verenigingen/pull/1226#issuecomment-5764383863),
which re-derives both halves (`7c0271d38` touches no `permissions` block; the grant is already
present in `2dbea04eb`). The fix in #1226 is unaffected — only its stated reason for leaving the
DocType permission alone was wrong, and the corrected reason is "provenance unknown", not
"deliberate".

**2. A leak was blamed on a harness quirk by a control that did not discriminate.** A new
test module leaked `Member` rows. A reviewer defended it as pre-existing, having reproduced
the identical warning on unmodified `develop` using a *different* test. Convincing, and
useless: that observation is equally consistent with "harness quirk, this test is innocent"
and "harness quirk exists **and** this test also leaks, because it commits."

Measured properly, same command, nothing else changed:

| | Member rows leaked |
|---|---|
| with `frappe.db.commit()` in tearDown | **2** |
| without it (run 1) | **0** |
| without it (run 2) | **0** |

The commit was not preserving cleanup, it was **causing** the leak — freezing whatever the
drain had not yet cleaned, turning a transient lock-contention race into a permanent leak.
Then the sibling used as the original control, which still carries the same commit, leaked
on the very next run. Filed as **#1233** (class) against **#1137** (its known instance).

**3. A fix measured the harm it prevented and not the harm it caused.** #1217 — the SEPA
loader never excluded invoices already in an open batch, so one could be collected twice.
The fix added the exclusion. Measured on veg11 **before merge**: 13 invoices excluded, of
which **6 were stranded** (Draft, no SEPA file, past batch_date) and would have become
permanently uncollectable — silently, no operator signal, no recovery path a Staff user
could take. The PR traded double-collection for non-collection of comparable size.

A canonical carve-out already existed — `sepa_constants.stranded_batch_exclusion()`, three
production callers, its own comment recording the same measurement on veg11. Folding it in
took 13 → 7, freeing exactly the 6. **When a fix works by excluding, measure the inverse
harm on real data, and grep for an existing carve-out before writing one.**

---

## What shipped

| PR | Issue | What changed |
|---|---|---|
| #1198 | #884 | Monthly/Quarterly catch-up billing runs on the member's own cycle, not the calendar grid |
| #1197 | #925 | An expelled volunteer actually loses their roles; reactivation re-derives current entitlement |
| #1202 | #1051 | Application status no longer discloses email / status / admin review notes to any caller |
| #1216 | #1212 | Deleted 14 dead-on-arrival E-Boekhouden endpoints + 51 tests, after confirming the live replacement is richer |
| #1226 | #1221 | The Load Unpaid Invoices button is hidden from users who cannot pass its gate |
| #1228 | #1217 | The loader excludes already-batched invoices, without stranding past-dated drafts |

`develop` verified green after each merge batch, including the push-only gates
(`Push on develop`, `Code Validation`, `Security Permission Check`) that pass on a PR and
fail after merge.

**#1231** (#1224) — approved after two review rounds; all 52 checks green, **merged
2026-09-21T17:03:49Z** as `2747428a0`. (This line said "pending, merge when green" when the
handoff was written.)

**Held deliberately:** **#1201** (#906) — correct, three real defects fixed, converted to
**draft**. It fixes a function nothing can reach (`Member` has no `application_invoice`
field, so its caller's guard is always False). Merging banks no value and leaves **#1204**
latent behind it — an unallocated refund Payment Entry permanently overstates the customer
receivable (measured 77.0 where it should be 0.0, no reconciliation path back). **Unblock
condition: the `application_invoice` gap closed AND #1204 resolved.**

---

## Two features were dead, and one was supposed to stay that way

Two of the four issues in the first batch turned out to be defects in **unreachable** code
(#906's refund path, #1206's `reactivate_user_account_safe` with zero non-test callers).
That prompted a sweep, which produced censuses **#1210** (UI/route) and **#1211**
(server-side, partial — whitelisted functions swept exhaustively, others only by hand).

The important correction came from the maintainer, not the sweep: **#1207 found "Submit to
Bank" has never worked, and it should not be fixed** — there is no API connection to the
bank, so repairing the whitelist would expose a button that fails for a deeper reason. A
dead feature may be dead on purpose. #1212 was likewise deleted rather than re-wired once a
live replacement was established.

**Before fixing a defect, establish the code can execute and the feature is wanted. Before
restoring anything dead, find out why it died.**

---

## Issues filed (31 — the ones worth knowing about)

**Money / correctness**
- **#1204** unallocated refund PE overstates the receivable, no reconciliation path *(blocks #1201)*
- **#1207** SEPA "Submit to Bank" + "Mark Invoices as Paid" never worked (doc-bound methods, undecorated) — *Submit to Bank is WONTFIX per maintainer; `mark_invoices_as_paid` is the live half*
- **#1217→#1222** four divergent copies of the "already in an open batch" predicate
- **#1218** loader has no membership/currency scoping — non-membership and non-EUR invoices offered to SEPA
- **#1219** the invoice cap truncates silently, no total-eligible count
- **#1232** `find_original_sepa_batch_for_return` omits the status filter its sibling has (the #399 sibling-query class)
- **#1199** refund PE references the fully-paid invoice it refunds *(fixed in #1201)*
- **#1200** three more Payment Entry sites missing `paid_from`/`paid_to`/`company`

**Security / access**
- **#1225** "Generate SEPA File" / "Validate Mandates" visible-but-unusable for Staff — *now routinely reachable because of #1231*
- **#1227** `load_unpaid_invoices_secure` drops the `as membership` alias, would leave a required Link blank
- **#1205** the guest return token has no expiry, and this payload (email + admin notes + staff name) is its heaviest caller
- **#1229** `ChapterRole.on_update` calls a HIGH-gated method internally and fails *silently*

**Dead / unwired**
- **#1206** the appeal-reversal path has zero non-test callers while its disable twin has two
- **#1208** Chapter "View Board History" — same undecorated doc-method mechanism as #1207
- **#1209** two more dead links; the payment-recovery funnel is dead end-to-end
- **#1213**, **#1214**, **#1215** — SEPA mandate wrappers, Automated Campaigns (**note: #1214's premise is corrected in its comments — it skips, it does not run generically**), Mollie customer link

**Test integrity**
- **#1233** a commit in tearDown causes the leak it cleans up *(class of #1137)*
- **#1223** `test_loaded_invoice_enriched_with_member_and_mandate` flaky on an unscoped limit
- **#1203** the pre-existing weak test that let #925 survive
- **#1230** `batch_log`/`status` mutated post-submit where neither field is `allow_on_submit`
- **#1196** `calculate_billing_periods_for_gap` has no Weekly/Semi-Annual case

---

## What I would pick up next

1. **#1225** — #1231 makes it routinely reachable. A Staff user can now submit a batch, then
   sees a primary-styled "Generate SEPA File" button that raises when clicked, and has no
   further action available. #1231 is honest that it is a step, not a completion.
2. **#1204 + the `application_invoice` gap** — together they unblock #1201.
3. **#1233** — AST-count the real population first. `grep` finds 171 files containing both a
   `tearDown` and a commit, but that is string co-occurrence, **not** a defect count.

---

## Traps worth not re-learning

- **There is no `verenigingen/hooks.py`.** Hooks are a package at `verenigingen/hooks/`.
  A grep for the file returns nothing *silently* — I made exactly that mistake and reported
  a vacuous "not found" until a control came back zero and exposed it.
- **`gh pr checks` summaries truncate.** A `| head -8` hid a real failure on #1231. Read the
  JSON, and print the failures explicitly before the pending list.
- **The order-dependence ratchet exempts commits by enclosing function NAME** (`COMMIT_EXEMPT`,
  the #825 defect). A green gate there does not mean the commit is acceptable. The right fix
  was to delete the commit, not regenerate the baseline — after which a full
  `--update-baseline` regenerates byte-identical, sidestepping #933/#934 entirely.
- **`MEMORY.md` is at its truncation cap.** Adding to it now requires trimming; four
  superseded lines were dropped to fit three new ones, leaving 120 bytes of headroom.

---

## Process note

Every PR needed a second round, and **not one was for its fix**: an activated data-loss path,
an untested branch of a security `or`, a ledger defect behind a green test, a stranded-invoice
inverse risk, a commit that caused the leak it cleaned. None was visible in a diff. All were
found by mutating the code and watching what *failed* to break.

The dispatch brief that produced this ordered the work **premise → red → fix → green → mutate
→ class sweep → self-review → then push**, with a standing instruction never to widen access
on a financial operation without explicit approval. Two agents stopped and reported instead of
implementing, and both were right to.

---

*Counts verified at write time: `gh pr list --state merged --search "merged:2026-09-21"` → 6 from this session (#1197, #1198, #1202, #1216, #1226, #1228); the other 9 merged today belong to the previous session. `gh issue list --search "created:2026-09-21"` → 31 at or above #1195. Every issue number cited above was checked to exist and to be open.*
