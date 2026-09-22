# 2026-09-22b — every blocking finding was in a test or an instrument

Three PRs merged, three open and awaiting CI, ten issues filed. Across eight independent
reviews and five self-reviews, **not one blocking finding was in a production diff.** Every one
was in a test that could not fail, a scanner that could not see, or a sentence in the
record that said something untrue. That is the third session in a row with this shape,
and at three it stops being an observation and becomes the thing to design against.

## What shipped, and what is still in flight

| PR | Issue | What it does |
|---|---|---|
| #1255 | — | the 2026-09-22 session handoff |
| #1259 | #1249 | `sepa_race_condition_manager` resolves the real Membership via the dues schedule |
| #1260 | #1253 | `match_by_batch_reference` requires `sepa_file_generated` |

Merged. Still open, review answered and independently verified, waiting only on CI:

| PR | Issue | What it does |
|---|---|---|
| #1263 | #1251, #1252 | DD batch child-table handlers rewired; dues-schedule alias renamed |
| #1265 | #1254 | the factory uniquifies an email only when it is actually taken |
| #1266 | #1250 (part) | `_cleanup_tracked_docs` cancels before force-deleting, with a ledger carve-out |

Filed: #1256, #1257, #1258, #1261, #1262, #1264, #1267, #1268, #1269, #1270.

## #1254 — a phantom flake that was a 1-in-135 dice roll, and the answer was already written down

`test_logged_in_own_member_can_read_via_own_id_param_with_no_token` failed once and
passed once on the same CI job, byte-identical tree, identical 17-module shard prefix.
The previous session could not reproduce it and, correctly, declined to invent a
mechanism.

`EnhancedTestDataFactory.create_member` rewrote a caller-supplied `email` whenever the
local part's **last five characters carried no digit** — a heuristic standing in for
"the caller did not uniquify this themselves". `frappe.generate_hash()` returns
lowercase hex, so a hash-suffixed local part draws a digit-free tail with probability
`(6/16)**5` = **1 run in ~135** (measured: 12/2000 on test_site_1). When it fired,
`Member.email` diverged from the string the test then built the `User` from,
`Member.user` was blank because the Member is created first, `get_member_name_for_user`
matched on neither, and the page took its refusal branch.

**The mechanism was already documented, one helper away.** `create_test_board_member`,
in the same file, appends a literal `0` to its hash with the comment *"the factory
rewrites Member.email unless the local part's last 5 characters contain one … breaks
user-linked lookups ~1 run in 135."* One helper was immunised and the trap was left live
everywhere else. **If a workaround deserved a comment, that comment is a search query.**

### The near-miss: the clock fit perfectly and was wrong

The failing run started 22:48 UTC and the passing rerun 06:53 UTC — straddling the
18:30–24:00 window where the UTC date differs from the site's Asia/Kolkata date, which
this repo has a whole documented bug class about. It fit exactly. It was a coincidence.
**A random mechanism produces the same two-run pattern as a time-dependent one**, so the
straddle discriminates nothing. Check what is actually random in a test — hashes,
`random_string`, uuid tails — and compute the rate, before reaching for the clock.

## The pattern, stated plainly

| where the defect was | what it was |
|---|---|
| #1266 round 1 | reintroduced #482's ledger stranding — the guard it needed sat **500 lines above in the same file** |
| #1266 round 2 | the new test passed with the entire mechanism deleted, backfilled by an unrelated `Member.on_trash` cascade |
| #1263 round 2 | the schema gate could not see a variable-held or object-literal field name |
| #1263 round 3 | the parser written to fix that produced **phantom** fields from nested objects *and* **silently dropped** spread keys |
| #1265 | my own test's sentinel only denied access *because of the bug I was removing* |
| #1260's record | "0 additional instances" was 1; a count of 12 whose own breakdown listed 10 |
| #1258 | a live defect **auto-closed by a sentence saying it was not fixed** |

Five production diffs, eight independent reviews, zero production defects found. The
reviews are still worth their cost — they caught a ledger-corrupting regression and two
tests with no regression value — but they are not finding bugs in the code. They are
finding bugs in what we believe about the code.

## The instrument that kept reproducing the failure it was built to prevent

#1263 needed a gate so a typo'd field name could not silently no-op again. Round 2 built
one from two regexes. Round 3's review showed it was blind to a variable-held name and
to `frm.set_value({...})`. Round 3 replaced the regexes with a hand-written
bracket-and-quote-aware argument parser. Round 4's review showed *that* harvested keys
from nested objects (phantom fields → false CI red on innocent code) and silently
absorbed spread/computed keys mixed with a literal one (dropped fields → the exact
failure it was built to stop).

Two rounds, two new defects, each in the code written to close the previous one. The
resolution was not a third parser:

> Treat **any** object-literal argument as unparseable and hard-fail. Delete the
> key-extraction. Keep the quoted-string-literal path, which covers all 17 live call
> sites.

Net deletion of parsing logic. It cannot produce a phantom field or drop one silently,
because it no longer claims to read anything it cannot read exactly. **A gate that
refuses what it cannot parse is strictly better than one that guesses**, and "this
scanner is not a JS parser" belongs in the docstring of every scanner in this repo.

## #1266 — the guard was in the same file, and then the test could not fail

Round 1 gave `_cleanup_tracked_docs` a cancel-before-delete step. Cancelling a
ledger-bearing voucher does not remove its GL/Payment Ledger rows — it **writes
reversals** — and `delete_doc` does not take them with the parent. Measured on
test_site_4: `GL 6→8, PLE 3→4`, parent gone. That is #482 exactly, which PR #518 already
fixed for the sibling drain, using `has_ledger_rows` — a guard sitting ~500 lines above
the new code, already imported at module scope.

Round 2 added the carve-out. Round 2's review then found the **other** new test passed
with the entire cancel-before-delete block removed: it tracked `Member` as well as
`Membership`, and force-deleting the Member fires `MemberCleanupService.handle_member_deletion`,
an unrelated production cascade that cancels and force-deletes the Membership anyway.
The round's self-review had answered "yes" to *"would each new test fail if the fix were
removed?"* — true of one test, not the other.

Round 3 tracks only the `Membership`. Verified independently, both directions:

| mutation | non-ledger test | ledger test |
|---|---|---|
| whole cancel-before-delete block removed | **reddens** | green |
| only the ledger clause removed | green | **reddens** |

### The structural result nobody had stated — #1270

A real submitted Sales Invoice always posts ledger rows (measured: 2 GL / 1 PLE for a
plain one). So the carve-out means cancel-before-delete **cannot** close the
dangling-link symptom for exactly the population #1250 is about — 134 Sales Invoices.
The two properties are mutually exclusive as the drain is currently designed. #1266
closes the non-ledger half honestly and does not claim #1250. The alternative nobody has
costed is link-aware delete ordering: Frappe already refuses a non-`force` delete when
something still links (verified), and the drain passes `force=True` straight past it.

## Two hypotheses killed by experiment, and the one that survived

#1267 reports that the `Bank Transaction.reference_number` unique-index patch silently
no-ops when duplicates exist. The index is present on **test_site_3 only**, absent on 1,
2, 4 and 5. I went looking for a competing explanation:

1. **"A later `migrate` drops it"** — #809's class, a unique index on a column declared
   `unique: 0` with no Custom Field. Fit well. **Refuted:** created the index on
   test_site_fresh, ran a full `bench migrate` (exit 0), re-checked — still there.
2. **"The `ALTER` is invalid on a TEXT column"** — the column is `text` everywhere and
   the statement carries no prefix length. **Refuted:** ran the patch's exact statement;
   it succeeded.

Both sites restored. What survives is the original mechanism plus the part that makes it
matter: **the patch is one-shot.** It is recorded in `Patch Log` whichever branch it
takes, so it never runs again. A duplicate lasting one `migrate` — on test_site_1 that
duplicate is `REF123`, a hardcoded **test fixture** (#1268) — permanently disables the
index, and cleaning up the duplicates afterwards does not bring it back. Any re-fix has
to be re-runnable, not a correction to that file.

## A durable fact: harness `cancel()` never fails on back-links

`Document.check_no_back_links_exist()` is the only generic guard that refuses to cancel a
document another submitted document references. It is gated:

```python
if not self.flags.ignore_links:
```

**Every** cancel-before-delete path in this harness sets that flag first (`base.py:414`,
`enhanced_test_factory.py:2188`). So "I cancelled a voucher another submitted document
referenced and it cancelled cleanly" is not evidence ERPNext tolerates it — it is
evidence the only objecting check was switched off. Two people independently failed to
trigger a cancel failure while establishing #1264's mechanism, and a failed reproduction
reads exactly like an absent defect.

## #1258 — a live defect closed by a sentence saying it was not fixed

PR #1260's body contained:

> `- Did not fix #1258's match_by_amount_and_reference gaps here -- filed instead.`

GitHub's auto-close parser matches the bare `fix #1258` and closed the issue on merge.
The defect — a status-only batch filter with no `sepa_file_generated` check, plus a
bank-supplied `reference` interpolated into a `LIKE` pattern where its wildcards stay
live (the #1153 class), feeding a Payment Entry writer at confidence 0.95 — is still on
`develop` at `bank_transaction_reconciliation.py:321`. Reopened with the evidence.

**A closing keyword is matched regardless of the surrounding words, including a
negation.** Write "tracked separately as #1258" when you mean it is not fixed here.

## Process notes against myself

Three claims of mine needed retracting today. The fixes held; the numbers around them
did not.

- **I invented a mechanism that fit and was wrong.** I found that `creation` on #1250's
  134 rows sits exactly 5h30m ahead of an epoch embedded in the schedule name — the
  Kolkata offset test sites carry while veg11 is Europe/Amsterdam — and posted it as
  evidence a test-configured process had written into veg11. **#642 shows veg11's own
  timezone was `Asia/Kolkata` until 2026-09-03**, months after those rows. The
  `Europe/Amsterdam` I measured is today's value, which is precisely why it looked
  discriminating. Corrected in the thread within the hour, but it was published first.
- **I repeated a figure I had not checked.** I carried #1250's "~€13.4k" into a dispatch
  brief and a summary. It is **€3,401.00**.
- **"16 files / ~35 call sites" was a property of my grep, not of the class** — and I
  missed a second cohort entirely. Literal emails with digit-free tails were rewritten
  **100%** of the time, not 1-in-135: **162 files / 515 literals** whose behaviour my fix
  changes deterministically. I shipped "no call-site edits are needed" on the strength of
  the wrong cohort.
- **And then that cohort broke CI, in the file I did not run.** Shard 7/12 reddened on
  `test_donor_permissions.py`. My flip-detector required the literal to also mint a
  `User`; that file uses `mock_roles`. I had run `test_donor_permissions_security.py` and
  not `test_donor_permissions.py` — two siblings, nearly identical names, the exact trap
  this repo documents. Worth noting the standard check *cleared* me: the shard log holds
  **zero** occurrences of my change's strings, because the breaking test never mentions
  my code.

  The test itself is the lesson. Its sentinel for "a user with the Member role but no
  member record" was the member's own literal email, which only denied access because the
  factory rewrote `Member.email` behind it — a side effect, not a property of the
  fixture. **The file said so in three separate comments, including the failing test's
  own.** It was not passing by accident; it was built on the bug. Fixed by making the
  sentinel unrelated by construction, plus a control that fails by name if it ever
  resolves again.

- **Choosing the environment is still part of the experiment, and it bit again on the
  first PR written after the handoff that said so.** #1266's income-account fixture had
  no currency filter; test_site_4's `_Test Company` has 4 Income Accounts (one EUR
  against an INR default), test_site_5 has 1. It passed on the author's site by chance
  and errored on the reviewer's *before reaching its own assertion*.

## Still open

1. **#1270** — the drain's two safety properties are mutually exclusive for a real
   invoice. Needs a decision on link-aware delete ordering, not another guard.
2. **#1258** (reopened), **#1267**, **#1268** — the reconciliation LIKE gap, the
   one-shot index patch, the fixture collision that trips it.
3. **#1264** — the delete-path census; #1250's actual mechanism is still unpinned, and
   `_remove_drained_record` (the drain nearly every test uses) is the likelier culprit.
4. **#1257** — `Sales Invoice.membership` written but populated on 0 of 3471 rows; two
   payment-history readers silently degrade.
5. **#1251's descendants** — #1261, #1262, #1269.
6. **#1204 + #1201** — unchanged for a third handoff running.

## The thing to design against

Three sessions, the same result: the code under change keeps being right, and everything
we build to *check* it keeps being wrong. The checks fail in a small number of repeatable
ways — a test satisfied by something other than the mechanism, a scanner blind to a shape
its author did not picture, a count that was a property of one grep, a sentence in a PR
body that a machine reads differently than a human. Each is cheap to catch **once you ask
the question**: mutate the fix away and watch; feed the scanner the shape you did not
write; re-derive the count with a different pattern; read the body as the parser will.

None of that is new advice — all four are already in `CLAUDE.md`. What is new is that
they are now the *only* place defects are being found, which argues for running them
first rather than last.
