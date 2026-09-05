# 2026-09-05 — the backlog over-reported by half, and a policy nobody had written down

Two findings dominate this session, and neither is a bug fix.

**Eleven of ~25 dispatched issues were already fixed.** Not stale in the sense of
"no longer relevant" — actually fixed, on develop, with the fixing commit citing
the issue *parenthetically* and therefore never closing it. Roughly 600k tokens
went into proving open issues weren't open. And we reproduced the same defect
ourselves six times before noticing.

**The billing model was never written down.** The association bills on RUNNING
periods anchored to each member's own cycle, with coverage dates as the ledger.
That single sentence, supplied by the maintainer in eight words late in the
session, immediately exposed one shipped-but-incomplete fix, one live
over-billing bug, and a whole class of tests structurally unable to detect
either. It is now in CLAUDE.md.

## What merged (23)

#820 #823 #824 #826 #827 #828 #833 #834 #835 #836 #838 #839 #843 #844 #847 #848
#849 #855 #858 #859 #862 #864 #869

Highlights, by consequence rather than order:

- **#869 (#207)** — catch-up billing split gaps at the book-year boundary, so an
  Annual period straddling 1 January was billed **twice**, and an offset 3-year
  gap billed as **four**. Confirmed live on veg11. Its first fix over-corrected
  (removing chunking under-billed multi-year gaps); review caught both directions.
- **#859 (#196)** — `bench export-fixtures` dropped ~57 of 63 custom fields,
  including `Sales Invoice.member` and `Customer.member`, because three unprefixed
  entries collided on one filename. The command `docs/ROLE_PROFILES.md:154` tells
  users to run.
- **#849 (#425)** — added weekly integrity sweeps for the two history tables that
  had none. Its **first draft would have erased `reason='MijnRood CSV import'`
  provenance on 476 rows, every week**. Caught in review.
- **#864 (#385)** — `secure_document_operation` reported `success=False` while a
  failed submit had already persisted `docstatus=1`.
- **#844 (#469)** — Chapter-save lock ordering. See the regression note below.

## Open and armed (11)

#871 #874 #876 #877 #879 #880 #881 #883 #886 #887 #888

`#874` is Mollie e2e coverage that **skips** without credentials — verified
structurally, and its PR body now says plainly that this coverage does not run in
CI. `#887` is an interim fix, see below.

## For next session

### 1. CI test failures — start here

`#887` raises a query-count cap **as an interim** to unblock develop. The real
issue is **#885**: #844's `_prelock_members_for_save` is called from inside each
handler rather than once per save, so **every Member is locked 6x**. Measured 277
queries against a 260 cap; pre-#844 tree gives 7/7 OK. Three options are laid out
there; the tempting one (memoise) is the dangerous one, because
`frappe.db.rollback()` releases locks. Put the cap back to 260 and re-measure.

`#871` was red on a co-tenancy failure — the module is 15/15 green on both its
branch and develop in isolation. A re-run was queued; if it fails **identically**
the failure is deterministic order-dependence and needs real work, if it passes it
was probabilistic. That distinction settled #852 and is worth applying by reflex.

### 2. The billing thread — one query answers three issues

**#890** (live over-billing), **#884** (Monthly/Quarterly anchoring), **#882**
(why the flat rate is correct) all wait on the same measurement:

> how many submitted Sales Invoices carry a `custom_coverage_start_date` /
> `custom_coverage_end_date` span that is not one period of their schedule's
> `billing_frequency`?

That count decides whether these are charging members incorrectly today or are
latent. Nobody has run it.

**#890 specifically**: the maintainer expected tests already covered this. They do
not, and the issue now asks *why* as the more valuable half — the hypothesis to
test first is that every fixture is anchored to a calendar boundary, where the
calendar and running answers coincide and the entire suite is structurally blind.

### 3. Follow-ups worth triaging (filed today)

Security-adjacent: **#878** (two bytes-vs-int rate-limit bugs, one a *verified
live bypass*, missed by an earlier sweep of that same class). Money-adjacent:
**#867** (`mollie_payment_orchestrator` singleton never invalidated — affects
bank/GL posting), **#872** (`PaymentTypeRouter`'s DONATION branch hard-coded to
`pending_implementation`, so bulk discovery counts every donation as skipped).
Class-wide: **#889** (`frappe.db.exists(dt, dt)` is always truthy for a Single —
~18 sites), **#875**, **#885**, **#825**, **#851**, **#852**.

### 4. Housekeeping

- `test_site_5`'s migrate is **blocked** by 52 leaked Payment Entries
  (`tr_webhook_test_12345` x42 and friends). Sites 1-4, 6-13 and `fresh` are
  healthy and current. Awaiting a decision before deleting submitted documents.
- Two **May 2026 stashes** sit on the shared stash stack. Harmless until someone
  runs `git stash pop`.
- veg11 needs `migrate` + restart to see today's merges (#811's Custom Field,
  #835's fields, #855's Select options).

## What I got wrong, and what it cost

- **`gh issue list --limit 100` against 148 issues** silently hid the 48 oldest.
  Every "oldest first" list for most of the session was "oldest of the newest 100".
  The real floor was three weeks earlier. A sort cannot repair a truncated fetch.
- **Three screens answered a subtly different question than the one asked.** #202
  (scanned JSON defaults; the mechanism was frappe auto-filling a *defaultless*
  Select with its first option), #209 (found the pattern, but it was unreachable
  and the premise itself was false), #351 (the patch file existed and was
  registered — and was a documented no-op). Rule adopted: **screen to
  de-prioritise, never to conclude.**
- **My agent brief was self-contradictory** — "do not poll" plus "do not end your
  turn waiting" leaves no legal move once something is backgrounded. Five of twelve
  agents stalled. The missing clause is *do not background it*; a single-module run
  is 15-60s. Also: **a reviewer spawned by an agent reports to the coordinator, not
  to its parent**, so the parent waits forever unless someone relays.
- **I force-pushed without the `cd <worktree> &&` prefix** — the exact rule I put in
  every brief. It hit the right branch only because the session cwd happened to be
  right.

## What worked

The skeptical review changed the outcome on **11 of 17** PRs, and three times
caught a fix that was worse than the bug it fixed: #827's `for_update` gap-lock,
#849's provenance erasure, #883's wiping of independently-issued volunteer
accounts. Where an agent reported "APPROVE with no findings", that was itself
informative.

Treating "already fixed" as a **success** rather than a failed task is what made
the eleven closes cheap and well-evidenced. Every one carries a measurement and a
commit reference, so the next grep finds the fix instead of the bug.
