# 2026-08-28c — "not mine" and "advisory" are labels, not verdicts

Two PRs merged: **#379** (`dcbbf9994`, the Mollie reversal work, #370) and **#641**
(`399c7f809`). Five issues filed (#635, #636, #638, #640, #642). `veg11` moved off
`Asia/Kolkata`. Both `CLAUDE.md` files corrected. One skeptical review dispatched, which
found five things and proved two of my claims false.

The session's failure is not in any of that. Twice I saw a signal, read the **label**
attached to it, and filtered it out without reading the thing itself. Both times the thing
was directly about the work I was doing.

---

## 1. "not mine" — I rebuilt a fix the maintainer had already merged

A monitor event went past:

```
PR#639 COMPLETE: 43/43 checks, 0 failing 4fa8fef78
```

I checked whether it was one of mine, decided it wasn't, and said so. I never read the
title:

> **fix(tests): the one-day-ahead guard made two tests a scheduled red hour**

That is the bug I had just diagnosed on develop and was, at that moment, building a fix
for. #639 was already green and merged before my #641 reached CI. When I finally tried to
merge, git told me — `CONFLICTING / DIRTY`, on exactly one file.

Both of us diagnosed the same arithmetic. `site_a_day_ahead_of_process` pinned the process
to `Pacific/Midway` (UTC−11) and the site to `Pacific/Kiritimati` (UTC+14) and argued in
its docstring that 25 hours, being "strictly more than 24", made the site *exactly* one
day ahead. It does not: above 24 hours the gap crosses a **second** midnight once the
process's local time reaches 23:00, which is UTC 10:00–11:00 — one hour in every 24.
develop went red inside it at 10:08 UTC, on two shards, three tests.

The remedies differed:

| | approach |
|---|---|
| **#639** (merged) | keep the 25-hour pair, weaken the guard to "site strictly ahead of process" — the property the assertions actually rest on, since they compare instants |
| **#641** (mine) | keep the strict one-day guard, change the pair to exactly 24 hours (`Pacific/Apia`, UTC+13) |

Both defensible. Theirs landed first, so I dropped mine wholesale — `git checkout --theirs`
on the lever file, leaving it byte-identical to develop — rather than argue for a competing
design. My 24-hour sweep test went with it: it asserted a property #639 deliberately does
not guarantee, so keeping it would have reddened the trunk.

**The cost was one command.** `gh pr view 639 --json title` would have prevented the entire
detour. "Is this mine?" is the wrong question for a monitor event; "what is this about?" is
the right one, and it is not more expensive.

### What survived, and why it was worth the detour anyway

Shard 5 of my PR failed on a test neither PR touched:

```
test_auto_submit_error_handling
AssertionError: Unexpected error during invoice generation: Bank import: debtor
'AmtTwo83214a' and amount 25.0 match 2 outstanding invoices ... Candidates:
ACC-SINV-2026-00002, ACC-SINV-2026-00001.
```

Nothing was wrong with the invoice generation. The test searched Error Log with

```python
{"error": ["like", f"%{invoice_name}%"], "creation": [">=", today()]}
```

and its own invoice was `ACC-SINV-2026-00001` — a name the **co-tenant's** message
contains, because that message lists candidate invoices. Two things make the filter too
wide, and both are repo-wide traps:

- **`tabError Log` is MyISAM**, so co-tenant rows survive their rollback and stay visible;
  `today()` does not exclude them.
- **Invoice numbering restarts at `00001`** on a fresh CI database, so the invoice-name
  filter is not the discriminator it looks like. Two tests in one shard get colliding,
  predictable names.

Confirmed rather than inferred: `test_bank_integration` owns the `AmtTwo` fixture and that
message, and it **is** a shard-5 co-tenant in the same log. It was also verified *not
flaky* first — an explicit job re-run reproduced it identically.

Now scoped by a timestamp taken before generation. One check mattered there: this bench
runs **three clocks** (below), so a timestamp filter is only sound if both sides use the
same one. Measured — `frappe.utils.now()` → `17:12:47`, the resulting row's `creation` →
`17:12:48`, row visible through `creation >= mark`. Had `Error Log.creation` been
DB-written, the fix would have silently excluded *everything* and still looked green.

---

## 2. "advisory" — a hard CI gate printed "Passed" and I believed the word

Pre-commit printed this next to my new method:

```
💾 Failed-Write Guard (ratchet) [advisory]...............................Passed

  webhook_wrapper_service_unified.py  UnifiedWebhookWrapperService._repair_reversal_history()
      line 1525: RETURNS_TRUTHY after [.save]
```

I read `[advisory]` and `Passed`, called it a false positive in my report to Foppe, and
pushed. CI failed on it. The hook is advisory; **CI runs the validator's own test suite**,
where `test_repo_is_at_or_below_its_baseline` fails on any occurrence above baseline.
Reproducible locally in ten seconds:

```bash
./env/bin/python -m unittest \
  scripts.validation.tests.test_failed_write_validator.BaselineTest
```

And it was not a false positive in substance either. The method returned the error string
on failure and `None` on success — **truthy meaning failure**, backwards from every other
shape in the repo and indistinguishable to the validator from a discarded write. I had even
flagged it to Foppe as something "a future reader may trip over" while arguing it was fine;
the right reading was that if it needs that caveat, it is the wrong shape. Now
`(ok, error)` — the `AccountCreationService` shape the validator calibrates against by name.

---

## 3. #379: what two rounds of skeptical review changed

Round 3 (relayed by Foppe) and round 4 (dispatched). Round 4 found five things and proved
**two of my round-3 claims false**:

- **I fixed one twin and left the other.** `process_refund_webhook` still carried the exact
  pattern S3 removed from `process_chargeback_webhook` — same file, 40 lines apart, in the
  commit whose message claimed to be sweeping for it. No production caller, but routing an
  *endpoint* around a defect leaves it in the service method for the next caller.
- **"There is nothing in such a payload to book from" was false.** The chargeback id is
  recoverable via `payment.chargebacks.list()`, which the app already calls
  (`unified_idempotency_manager.py:381`). The 2xx outcome stood; the *reason* did not — and
  the reason is what a future reader uses to decide not to implement it. Now
  `not_implemented`, following the file's own precedent.
- **My C2 fix bought visibility only**, and the repair was in the sibling I had *cited in
  my own comment*: `_process_pending_refunds` already collects the history row on its
  already-booked path, commented *"Skipping the booking must not skip the repair."*
  `process_reversal_webhook` returned early with none, so delivery 2 answered 200 with the
  row still missing, permanently. That comment was the search query and I did not run it.
- **My diff widened a latent crash** — `extract_webhook_ids` called unconditionally raised
  `AttributeError` on `{"id": None}`, `{"id": 12345}`, `{"chargeback": ["a"]}` → outer
  `except` → 500 → the retry storm the refusal exists to prevent. Hardened the extractor
  itself, since `handle_refund_webhook` had the same exposure.
- **C1's "load-bearing because of this PR" described a dark path.** The chargeback endpoint
  is not registered with Mollie and `json.loads` a body Mollie sends form-encoded, so a real
  chargeback dies in the outer `except` before reaching the guard. Filed as **#638**.

It also verified by mutation that the round-3 GL assertions and save-stub genuinely
discriminate, and independently confirmed the `test_mollie_gap_unified_webhook_handlers`
error is pre-existing site dirt.

Also worth recording from round 3: **two tests were green because of the bug.**
`test_unified_webhook_wrapper_service` drove the booker with a fake Payment Entry name, so
`donation_doc.save()` raised a Link error every run — the swallow hid it, and the tests
asserted the success contract while the row they check was never persisted. Fixing the
swallow correctly reddened them.

---

## 4. #640 — five hypotheses, all refuted, and the instrument that was missing

Six tests in `test_bank_transaction_reconciliation_coverage` failed **deterministically in
CI** — three runs including an explicit re-run, byte-identical shard-7 module set across
two commits — and reproduce in **no** local configuration.

| hypothesis | how it died |
|---|---|
| shard re-packing alone | module set byte-identical across two failing commits |
| in-process co-tenancy / ordering | replayed all 111 shard-7 modules in CI's order, one process: 2107 tests, 0 failing |
| `test_mollie_configuration_service` poisoning `Mollie Settings` | running it immediately before leaves the module green |
| gateway-credential parity (CLAUDE.md's documented trap) | `run_without_credentials.sh`: 68/68 green |
| fresh-site state | `test_site_fresh`: 68/68 green |

Six local configurations pass; CI fails three for three. **I guessed five times and was
wrong five times.** The useful output was the negative results and one tool.

### The instrument

`bench run-tests --module` runs one module per process, so it *cannot* reproduce in-process
co-tenancy at all. Subclassing frappe's own `ParallelTestRunner` and overriding only
`get_test_file_list` replays an arbitrary **ordered subset** in one process with CI's exact
setup and `before_tests` hooks:

```python
class OrderedSubsetRunner(ParallelTestRunner):
    def __init__(self, site, wanted):
        self.wanted = wanted
        super().__init__("verenigingen", site, build_number=1, total_builds=1)

    def get_test_file_list(self):
        by_dotted = {}
        for path, filename in get_all_tests("verenigingen"):
            after = "/".join((path, filename)).split("/apps/", 1)[1]
            by_dotted[".".join(after.split("/")[1:])[: -len(".py")]] = (path, filename)
        return [by_dotted[n] for n in self.wanted if n in by_dotted]
```

Run from `<bench>/sites` with the bench python. `get_all_tests` imports from
`frappe.parallel_test_runner`, **not** `frappe.tests.utils`. Full text in #640. It belongs
in `scripts/testing/`; reproducing a shard is otherwise impossible locally.

### The attribution, stated precisely

My code never executed in shard 7 — 0 of 113 modules appear in the diff, 0 reference either
production file changed, 0 hits for all 14 error/test strings introduced. What my branch
changed was the **partition**: editing test files re-packs every bin, so the module got new
co-tenants. develop's CI was green throughout.

So the honest sentence is **"exposed a latent fragility, not introduced a defect"** — and
that distinction does *not* make a branch mergeable. I spent a while asserting "not my
branch" partly on a local develop comparison run on a **dirty site**, which was weaker
evidence than I leaned on it for.

It resolved by merging develop into #379, which re-packed the shards again and turned
shard 7 green without a line of either module changing — the strongest confirmation of the
mechanism available. **#640 stays open**: the module is still fragile about ambient
`Mollie Settings`, and it will redden whoever's PR next repacks it.

---

## 5. #642 — the site's clock, and a third one nobody mentioned

`System Settings.time_zone` was `Asia/Kolkata` — Frappe's install default — on `veg11` and
every test site. UTC+5:30 means the site's day rolls at 18:30 UTC = **20:30 Dutch**, so
anything stamped in the evening records tomorrow's date.

### There are three clocks

| clock | offset |
|---|---|
| real UTC | — |
| `frappe.utils.now()` — writes `creation` | **UTC+5:30** |
| MariaDB's own `NOW()` | **UTC+2** (host CEST) |

The app and the database disagreed by **3.5 hours**. Any raw SQL comparing an app-written
timestamp against DB-side `NOW()` is wrong by that much. Still live wherever the site
timezone differs from the DB host's; `sepa_mandate_member_integration_service.py:194,227,252`
writes `modified = NOW()` into app-clock columns, which is worth a look given Frappe compares
`modified` for optimistic locking. **Unverified** — a grep, not a measurement.

### The measurement right-sized the fix

Rows *created* in the window are not rows with a *wrong* date; the date is only wrong if
stamped from `today()`. Splitting three ways:

| field | in window | **Kolkata** date | **Dutch** date | other |
|---|---|---|---|---|
| `Sales Invoice.posting_date` | 644 | **627** | **0** | 17 |
| `Membership.start_date` | 402 | **248** | **0** | 154 |
| `Payment Entry.posting_date` | 31 | **31** | **0** | 0 |
| `Donation.donation_date` | 10 | **10** | **0** | 0 |

Zero rows anywhere carry the Dutch date. But only **four documents** crossed a *month*
boundary — three Sales Invoices and one Payment Entry, all one automated batch at 21:39 on
30 June, June revenue booked into July. None crossed a year. Counts identical with a flat
3.5h offset and a DST-aware one, so not a summer-only lower bound.

Decision (Foppe): change the setting, rewrite nothing. `veg11` is now `Europe/Amsterdam`;
`today()` moved `2026-08-29` → `2026-08-28`, verified in a fresh process.

### Test sites cannot hold it — and should not

All six accepted the change and reverted. Isolated by experiment:

| action | result |
|---|---|
| set it | `Europe/Amsterdam` |
| run a unit module needing no test records | **survives** |
| run a module needing test records | **reverts to Kolkata** |

The reverting run prints why: `ImportError: cannot import name 'before_tests' from
'erpnext.setup.utils'` followed by `Duplicate entry 'Standard Buying'`. **ERPNext's
`before_tests` runs the setup wizard, which resets `time_zone` to its default.** That is
why every test site was Kolkata to begin with.

This is fine. CI builds fresh, so `before_tests` sets Kolkata there while the CI *process*
runs UTC — preserving the process/site skew the #628 levers need. Making them agree is what
we deliberately wanted to avoid.

---

## 6. `CLAUDE.md` was wrong about veg11

Both copies said veg11 **is the live site**. Foppe: *"veg11 isn't a live site, it's just a
test site with production data for testing purposes."* That framing made me treat a routine
setting change as risky production work and stop halfway through an instruction.

Corrected in both files (7 edits each): veg11 is a test site carrying a copy of production
data — not production, no real users — but the data is worth keeping, so no test suite, no
`reinstall`, no bulk deletes. The "served out of the git working tree" claim is true and
was kept.

**Neither `CLAUDE.md` is git-tracked** (`~/CLAUDE.md`, `~/frappe-bench/CLAUDE.md`), despite
being presented as "checked into the codebase". This correction does not propagate. The
repo has `apps/verenigingen/CLAUDE.md`, untouched.

---

## Open

- **#640** — the shard-7 module. Open deliberately; read it before diagnosing a red shard-7.
- **#642** — remaining: the 3.5h app/DB skew, `modified = NOW()`, and doctypes beyond the
  four counted.
- **#638** — the chargeback endpoint is unreachable (unregistered URL, JSON parse of a
  form-encoded body, booking still a `TODO`).
- **#635 / #636** — the dues-reversal booker and the insert-first key reservation, the two
  halves of #370 that #379 does not close. **#370 stays open.**
- **A stale note of mine** calls a `git checkout` on veg11 "a live deploy" — same wrong
  framing as the `CLAUDE.md` line, not yet corrected.

## The rule

Both failures this session were the same move: **I read a label and skipped the thing.**
"not mine" on a monitor event, "advisory / Passed" on a validator. Neither label was
lying — #639 genuinely wasn't mine to fix, and the hook genuinely does pass. Both were
answering a narrower question than the one that mattered.

The cheap correction is the same in both cases: when a signal arrives about work you are
doing, spend the one command it takes to read what it actually says.
