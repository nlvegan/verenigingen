# Handoff — 2026-08-11

## The Select-field bug class, and the end of the `in_import` harness

Started as "continue with #280". The interesting finding is not any one fix: it is that
removing one test-harness flag exposed **nine production defects of a single shape**,
across five subsystems, that had been invisible for as long as the harness existed.

---

## 0. State at handoff

`develop` is at `c4dbd478`.

| PR | What | Merge commit |
|---|---|---|
| #283 | Mollie audit rows silently discarded (`webhook` / `api` not Select options) | `f606f5b1` |
| #286 | seven production paths writing invented values into Selects (closes #285) | `65a4770f` |
| #287 | account-mapping notes had no field; account-type overloaded onto `document_type` (closes #284) | `eddb7ccb` |
| #280 | `EnhancedTestCase` no longer suppresses production document behavior | `c4dbd478` |

Open PRs: **#282** (the previous handoff — still unmerged).
Open issues: 26 (−#284, −#285).

veg11 serves the git working tree, which is on `develop` and clean. The six doctypes
touched by #286/#287 were reloaded on veg11 and **verified live** (see §5).

---

## 1. The through-line: `_validate_selects()` is gated on `in_import` alone

`EnhancedTestCase.setUp` set `frappe.flags.in_import = True`. That flag gates four
separate behaviours in `frappe/model/document.py` (mapped in the 2026-08-10 handoff),
but the one that mattered here is:

```python
def _validate_selects(self):
    if frappe.flags.in_import:
        return
```

So for the entire life of that harness, **a test could write any string into any Select
and it would persist.** Production could not. Every place the app wrote a value the
Select did not declare was therefore invisible to the test suite *by construction* —
including places that had thorough, passing "the row is persisted" coverage.

Nine such defects were found. They share an exact shape:

> a caller-supplied or invented string assigned to a `Select`, with the resulting
> `ValidationError` either swallowed by a broad `except` or reported as something
> unrelated.

The swallow is what made them survive. In most cases the caller saw `success: True`.

### The nine

| # | Where | Effect in production |
|---|---|---|
| 1 | `MollieAuditLogger` wrote `"webhook"` / `"api"` | **every** Mollie webhook and API audit row silently discarded (#283) |
| 2 | `setup_default_payment_mappings()` builds `Receivable` first; Select offered `Bank`/`Cash` | **no default payment mappings ever created, for any company** |
| 3 | `SEPAErrorHandler.create_retry_batch()` copied `operation.__name__` into `operation_type` | **no SEPA retry batch could ever be saved** — even the hardcoded `"unknown"` fallback was not an option |
| 4 | `sepa_batch_processor` sets `status = "Partially Failed"` | the partial-failure state was unrepresentable; the save recording it threw inside a `log_error`-only `except` |
| 5 | `Volunteer Skill.proficiency_level` declared `"default": "3"` | **any skill row saved without an explicit level was rejected**, desk form included |
| 6 | `create_volunteer_from_member()` copied `skill.get("category")` verbatim | an unknown category failed the **entire volunteer creation**, not just the row |
| 7 | `membership_type.py` appended `default_warehouse: None` | `_set_defaults()` fills child rows, so the user's warehouse landed there and ERPNext rejected it — surfaced to the user as *"check permissions"* |
| 8 | `patches/v1_0/add_membership_analytics.py` asked for a `"Manual"` snapshot | the patch "succeeds" while the snapshot it exists to create is skipped |
| 9 | `add_account_mapping()` wrote free-text `notes` into `transaction_category` | the save is rejected; when a note *did* match an option it **overwrote a field the migration reads** (#284) |

**#2, #3 and #5 are the ones worth internalising.** Each is a feature that has never
worked once, in any deployment, and each had passing tests.

---

## 2. The rule this produces

**A regression test for this class must not use `EnhancedTestCase`.**

It is not a matter of writing a better assertion — that harness *cannot* observe the
defect, because it disables the validation that produces it. Use
`VereningingenTestCase` (`verenigingen/tests/utils/base.py`). #281, #283, #286 and #287
all made this choice.

Add the class to an **existing** test module. A new test *file* re-partitions all 12
shards (#248, four instances and counting).

### Prefer the invariant to the instance

Several of the new tests assert a property rather than a case, which catches the *next*
occurrence instead of re-catching this one:

- every `batch.status` literal `sepa_batch_processor` assigns is a declared option
- every frequency in `billing_period_calculator.valid_frequencies` is a schedule option
- every `event_type` option has a dispatch branch in `apply_event()`
- every `event_category` literal in the Mollie audit module is a declared option (#283)

These read the module source with `inspect.getsource` + a regex. Cheap, and they fail on
drift in either direction.

### `coerce_select_option`

New in `verenigingen/utils/select_options.py`:

```python
coerce_select_option(doctype, fieldname, value, fallback)
```

Use it at boundaries where a string arrives from outside — an API caller, an import, a
Python function name. It checks the **fallback** against the options too, so a wrong
fallback fails loudly instead of relocating the rejection.

Do **not** reach for it to silence a validation error inside the app's own code. Where
the app controls the value, the value should simply be right.

---

## 3. What `in_import` was actually hiding (the test side)

#280 went **118 → 29 → 15 → 10 → 0** CI failures. The test-side causes, in rough
frequency order:

1. **Invented Select values in fixtures** (~30). Mostly plausible-looking: `"Fee Change"`
   is a real value — of `Contribution Amendment Request.amendment_type`, a different
   field. Always pick the replacement from **what production writes**, not from the
   options list alone.
2. **ERPNext date rewriting.** `in_import` made `validate_posting_time()` overwrite
   `posting_date` with today and `validate_due_date()` move a past `due_date` *forward*.
   Fixtures that thought they were creating overdue invoices were not. Fix:
   `invoice.set_posting_time = 1` plus a genuinely backdated `posting_date`.
3. **Name preservation.** `set_new_name()` (`naming.py:158`) keeps a preset `name` under
   `in_import`, so `member.name[:8]` was `"Assoc-Me"` for every member, and a Customer
   name clash hit the primary key instead of being resolved by suffix.
4. **Skipped defaults**, including on **child rows** (`document.py:1078-1084`). A
   `Check` field default of `1` not being applied is how
   `test_termination_execution_workflow` avoided a 12-month commitment period it should
   always have hit.
5. **Unreachable branches asserted as covered.** See §4.

---

## 4. Two tests that could not be fixed by swapping a value

Both covered a branch `in_import` made reachable and production cannot reach. Worth
recognising the shape, because the instinct is to patch the fixture and move on.

**`test_unknown_event_type_returns_failure`** poked `"Frobnicate"` past validation with
`db.set_value` to reach `apply_event()`'s "Unknown event type" guard. `event_type` is a
required Select whose options are *exactly* the four the dispatch chain handles, so no
persisted event reaches that branch — and if one did, the guard's own failure path calls
`event.save()`, which the same Select rejects. **The guard is only reachable for a
document that cannot record the outcome.** Replaced with the invariant it exists to
protect.

**`test_duplicate_name_collision_is_handled_without_raising_to_caller`** asserted a
Customer name clash raises `DuplicateEntryError`, is swallowed, and returns `None`.
ERPNext resolves name clashes by appending a counter, so the insert succeeds. While
rewriting it: that `except frappe.exceptions.DuplicateEntryError` branch is **not
reachable at all** — `custom_mollie_customer_id` carries a *non-unique* index, so the
concurrent-insert race it documents cannot raise either. Left in place as harmless
defensive code, but no test claims to cover it now.

### Also: `billing_cutoff_frequency` vs `billing_frequency`

Two different fields, and they resolved in opposite directions:

- `billing_frequency` **gained** `Weekly` — the calculator lists it in
  `valid_frequencies`, handles it in four places, the SEPA batch processor and two
  reports branch on it, and the amendment annualiser has a 52.0 factor for it. Only the
  schema disagreed.
- `billing_cutoff_frequency` did **not** — `Weekly` is genuinely not a cutoff frequency.
  Its fallback branch is reached by the one storable value matching none of
  Monthly/Quarterly/Yearly: the **empty first option**, i.e. an unconfigured site.

When a test needs "an unrecognised value", check whether the Select has an empty option
before concluding the branch is untestable.

---

## 5. Operational notes

**Verify the failing direction.** For #286 and #287 the production changes were reverted
with the tests kept, to confirm every new test actually fails without the fix (6 modules,
then 5 tests). Twice this caught a test that would have passed either way.

**Doctype JSON is edited directly, no `modified` bump** (precedent `c0029069`); the
reload is content-hash based. To load a worktree's JSON into a test site without touching
the main checkout:

```bash
PYTHONPATH=<worktree> bench --site test_site_1 reload-doctype "<Name>"
```

**veg11 is the working tree, so `git pull` on develop is a deploy** — but only for
Python. Schema changes need an explicit `reload-doctype`, and adding a field needs the
column created. After merging, all six affected doctypes were reloaded and read back
from the live site; `notes` was confirmed present as a real column on
`tabE-Boekhouden Account Mapping`.

**Controller size is ratcheted per file.** `volunteer.py` went 5 lines over its 1,020
limit and CI failed on it. `python3 scripts/check_controller_size.py` runs the same check
locally; it counts code lines, not raw lines.

**Pre-commit traps that cost time here:**
- a formatter hook (black/ruff) that rewrites a file **aborts the commit** — re-add and
  re-commit
- `test-quality-enforcer` runs on the **whole staged set**, so pre-existing violations in
  a file you merely touched will block you. Verify they are identical on `develop`, then
  `SKIP=test-quality-enforcer`, and say why in the commit body
- it also runs at **pre-push**, so the same `SKIP=` is needed there

**Local warm-site pollution is not a branch effect.** Two full failure sets here were
environmental: a leftover hardcoded `Test Alert Rule` (8 errors) and a dangling
`Cash - TEMS` default account from a deleted test company. Both pass on CI. Before
attributing a local failure to the branch, check whether the test appears in the parsed
CI failure set at all.

---

## 6. Suggested next steps

1. **Merge #282** — the previous handoff is still open and its content is now history.
2. **The `Weekly` billing frequency is now selectable but untested end-to-end.** The
   calculator and reports have always handled it; no dues schedule has ever *used* it.
   An integration test that runs a weekly schedule through invoice generation would be
   worth having before anyone configures one.
3. **`apply_suggested_mappings()` still drops `suggested_type` and `confidence`.** Now
   that `E-Boekhouden Account Mapping` has a `notes` field, the confidence note has
   somewhere to go; the ERPNext account type still does not. Decide whether that concept
   deserves a field or should be dropped from the suggester.
4. **The swallow, not the Select, is the real bug class.** Every one of the nine was
   survivable only because a broad `except` reported success. The swallowed-exception
   ratchet (#241) counts these; consider whether the audit/insert paths in particular
   should be moved off it.
