# 2026-08-26b — the discriminator I declared dead

Nine PRs merged: seven handoffs (#564, #565, #577, #579, #580, #587, #591), plus **#592**
(`fc693de03`, #589) and **#595** (`3c89ceec3`, #581). One open: **#598** (#584), four
commits, and the last three of them exist because I was corrected — twice by a reviewer,
once by CI. Four issues filed (#593, #596, #597) and one closed as a duplicate I should
never have opened (#594). 23 orphaned SEPA Mandates deleted from veg11.

The session's failure is not any of the numbers. **Every measurement I made held.** What
did not hold was a conclusion I drew from a search that stopped one candidate too early —
and the evidence that refuted it had been sitting in the repo the whole time, written down
in a docstring, in a test named for the exact scenario.

---

## The lead: I proved ONE discriminator was dead and reported that NONE existed

#584 is "a member with two Active SEPA Mandates gets an arbitrarily chosen IBAN debited".
The existing guard blocked a second Active mandate only when the IBAN matched, justified in
its own docstring: a bank switch legitimately produces two, and the older one *"supersedes
via the Member SEPA Mandate Link `is_current` flag"*.

I went after that flag and demolished it properly. Measured on `test_site_1`:

- inserting two Active mandates with different IBANs is **accepted**, and the auto-sync
  writes `is_current = 1` for **both** — the flag is computed as
  `1 if status == "Active" and is_active`, in both writers, so it is *derived from* Active
  and cannot discriminate between two Active rows;
- `MemberSEPAMandateLink.check_current_mandate`, the only code that clears a sibling
  automatically, is **never called** — 0 invocations from a spy on the bound controller
  class across two inserts plus an explicit `member.save()`. Frappe does not run
  child-DocType `validate()`. The spy had a control: an explicit `run_method("validate")`
  fired it and raised `AttributeError: 'str' object has no attribute 'sepa_mandates'`,
  exactly as predicted, so the zero was discriminating and not a dead probe.

All correct. All still true. Then I wrote: *"there is no discriminator."*

There was. `SEPA Mandate` carries `used_for_memberships` / `used_for_donations` /
`used_for_other` as independent checkboxes, and they are live and load-bearing. CI found it
for me, in the form of a test that already existed:

> `test_payment_history_writer_parity.test_mandate_resolution_matches_with_newer_donation_only_mandate`
>
> *"PaymentHistoryService.\_get_default_mandate() used to delegate to …
> SEPAMandateManager.get_default_mandate(), which picks the single most-recently-created
> ACTIVE mandate **with no purpose filter at all**. The incremental writer … **has always
> filtered on used_for_memberships=1**. Those two mechanisms pick DIFFERENT mandates when a
> member has an active donation-only mandate that is newer than their active membership
> mandate. Fixed by making the rebuild path's \_get_default_mandate() filter on
> used_for_memberships=1 too."*

A regression test, for this exact ambiguity, whose fix was **filter by purpose** — the
opposite of the rule I had just built. Its docstring is the answer to the question I asked
the maintainer to decide.

> **"No X exists" is a claim about a search, not about the system.** I searched for the
> mechanism the *docstring named*, found it dead, and reported the category empty. The
> correct sentence was the narrower one: *"the `is_current` mechanism is dead."* Rule 4
> already says write the narrower sentence; it applies to absence claims most of all,
> because an absence claim is what licenses deleting a capability.

Cost: a design the maintainer approved on my evidence, an implementation of it, a skeptical
review of that implementation, and **26 CI failures** — of which perhaps four were tests
that needed changing anyway.

### What would have caught it in 60 seconds

`grep -rn "used_for_memberships" --include=*.py | grep -v tests` — **29 non-test
references across 13 files**, including `has_active_mandate(member, purpose=…)`. I never
ran it. I had already decided the answer.

---

## The correction, and what it actually looks like

One Active mandate per member **per purpose**. A member may hold a membership mandate and a
donation mandate at once — the capability the app models — and may not hold two of either.

- `validate_single_active_mandate_per_purpose` rejects an overlap and names **both** the
  blocking mandate and the purpose, because "you already have one" is unactionable when a
  member legitimately has two.
- `unambiguous_active_mandate(member, title, purpose="used_for_memberships")` filters
  *before* it counts. Both batch read sites resolve mandates for membership invoices (they
  join through `Membership Dues Schedule`), so the default fits; a still-ambiguous pick is
  **refused and logged**, never ordered.
- `cancel_active_mandates(member, reason, purposes=…)` supersedes only overlapping
  mandates. Re-signing for memberships must not cancel a donation mandate.

The 26 failures divided into three shapes, and the split is the useful part:

| shape | count | what I did |
|---|---|---|
| tests literally *about* holding several mandates | 5 | gave them two **purposes** — subject preserved, not deleted |
| loops testing a per-mandate property (IBAN, holder name, type, ID format, usage history) | 12 | one member per iteration |
| `test_sepa_xml_compliance` | 9 | one member per mandate in `_ensure_mandate` — a batch has one row per debtor in reality |

Only the middle group was ever "a test that needed updating". The first group would have
been **capability deletion disguised as test maintenance** — and it is the group whose names
(`test_multiple_mandates_per_member`, `test_detects_multiple_current_mandates`) were the
loudest available signal that the design was wrong.

> **When a contract change breaks tests named for the thing you are removing, that is not
> friction. That is the codebase disagreeing with you.**

---

## The skeptical review found the class was 4× the diff — in the file I was editing

Before CI got involved, the review of the first #584 commit found the change stopped at
**2 of 5 activation flows and 2 of ~6 read sites**. The worst:

**`validate_invoice_mandate` sat 40 lines below `get_invoice_mandate_info`, in the same
file, with the identical `ORDER BY sm.creation DESC LIMIT 1` over a member given by name.**
Both files. And it is the *more* consequential twin: `direct_debit_batch.js:268` calls the
one I fixed for a single row, while `:578` calls the one I missed **in a loop over every
invoice in the batch**, writing the same four SEPA-XML fields.

It also found:

- two whitelisted financial endpoints (`create_sepa_mandate_from_bank_details`,
  `create_and_link_mandate`) that **raised where develop succeeded** — measured on both
  trees. The first superseded nothing and was a third manufacturer of the bug; the second
  superseded only mandates matching the *calling* purpose, which is the shape the final
  design adopted;
- **one of my own tests that did not test its docstring.** `test_get_default_mandate` said
  "the Active one is returned and the Cancelled one is not", but created the Cancelled
  mandate first, and `get_active_mandates` orders `creation desc` — so creation order alone
  satisfied it. The reviewer deleted the status filter entirely and it stayed green. Two
  lines (swap the creations) made the filter load-bearing.

The same review had already killed all eight of my new tests with its own mutations, so the
tests were sound and the *coverage* was not. Those are different properties and I had only
checked one.

---

## The regression I introduced in the #581 fix, caught the same way

PR #595 (#581, merged `3c89ceec3`) had the identical shape: my fix worked and my fix broke
something else. I replaced an early-return-without-commit with a guarded `set_value` plus an
**unconditional** `frappe.db.commit()`. That helper is reached from
`test_sepa_reconciliation._owned_bank_account()` → `_make_bank_transaction`, which has **34
call sites in test bodies**, and committing there commits the test's in-flight fixtures.

Isolated with a control — TEST-LEAK count for that module on `test_site_3`:

| tree | leaks |
|---|---|
| develop | 3, 3, 3 |
| my commit | **6, 6, 4** |
| commit moved inside the guard | 3, 3 |

Three comments in this repo already forbid exactly this, each naming that helper
(`ReconBase.setUpClass:97`, `test_invoice_candidates.py:34`,
`support/invoice_payments.py:41`). I read none of them.

> **Leak-count-with-a-control is the instrument for "did my change add a commit".** Run the
> module N times on the branch and N on develop, `grep -c TEST-LEAK`.

The same review also corrected my severity framing: the five production readers of
`Company.default_bank_account` all exist, and every one is a **last-resort fallback** behind
both a configured setting and a named-account lookup, on a **test-only** company. I had told
the maintainer #581 "has production reach". It does not. The payoff was test determinism,
which is what the issue itself had argued.

---

## Process traps, three of them new

**1. CI runs a duplicate-helper gate that pre-commit does not.** After the ratchet,
`code-validation.yml:334-345` regenerates the baseline and fails if the file changes. The
ratchet *itself* exits 0 for a name-only collision — it correctly reports the bodies are not
near-identical — so a new helper called `_make_mandate` or `_delete_doc` passes locally and
reddens CI. Fix by **renaming**, not by recording a coincidence in the baseline. Hit twice
today.

**2. `gh run view --job <id> --log` returns 0 bytes while the run is in progress**, and
returns 0 bytes *silently*. Every grep against it then reads as "not there". The working
route is `gh api repos/:owner/:repo/actions/jobs/<id>/logs` (1 MB, complete). The
authoritative failure list is the `##[error]This change introduces test failures not in the
baseline:` block — the check-run **annotation** truncates before the list, so the annotation
is useless for this.

**3. "A finding is a class" applies to the TRACKER, not just the code.** I filed **#594**
for the ERPNext `is_company_account` gating and re-derived the whole thing from scratch.
**#544 had documented it since 2026-08-23**, with a better experiment (A/B/C inserts *with
the control*) and the two production call sites mine omitted. 97 open issues means the class
is probably already filed. Before opening one:

```
gh api 'repos/:owner/:repo/issues?state=all&per_page=100' --paginate \
  --jq '.[]|select(has("pull_request")|not)|"\(.number)\t\(.state)\t\(.title)"' | grep -i <mechanism>
```

Grep the **mechanism**, not the file name you happen to have. (`gh issue view` is still
broken here — Projects-classic GraphQL error — so `gh api` for everything.)

---

## veg11: 23 orphaned mandates deleted

94 → 71 SEPA Mandates. All 24 member-less Active mandates were test artifacts (`TEST-`,
`DUP-MAND-`, `NORM-`, `WORKFLOW-`, `EXIST-IBAN-`, `COMPAT-`, `ENHANCED-`, `ONEOFF-`; all
draft; all Administrator; 2026-02-21 → 05-29).

Method, because the shape is reusable: enumerate **every** Link and Dynamic Link field in
the schema that can point at the doctype (141 of them), count references to the targets, and
**run the same sweep against non-orphans as a control** — it found references in three
tables, which is the only reason "no references" meant anything. Exactly one orphan was
referenced (`18kgomn43i`, by draft Donation `Assoc-Dnt-2026-00126`); it was skipped, and
`refused: {}` confirmed Frappe's own link check blocked nothing the sweep had missed.
Backup first: `20260826_215907`.

**Still open:** whether to delete that Donation and its mandate. Both look like test data.

---

## State

| | |
|---|---|
| **#598** (#584) | open, 4 commits, head `5529af491`. The 26th failure (`test_renewal_with_sepa_mandate_changes`) was fixed after the last CI run — **that run is not yet re-verified green**. Check before merging. |
| **#592** (#589) | merged `fc693de03` |
| **#595** (#581) | merged `3c89ceec3` |
| veg11 | synced to develop; 23 orphan mandates deleted; 1 referenced orphan left |
| worktrees | `584-single-active-mandate`, `581-bank-account-ownership` — both clean, both mergeable |

**Filed:** #593 (dict-of-zeros swallows; one tells the user "No retry requests to process"
when the queue crashed), #596 (**15** child DocTypes with a `validate()` Frappe never calls
— two would raise if they ran), #597 (four more recency sites, two of them bulk batch
queries).

**#584 has a comment recording three deviations** from the original instructions: the
refusal helper was written fresh rather than reusing `log_ambiguous_refusal`, the patch
reports rather than throws (no index exists to protect — MariaDB has no partial unique
index — so a throw would block migrations to prevent nothing), and the purpose-scoping
decision itself.

---

## For whoever picks this up

1. **Verify #598's CI is green, then merge.** The last commit fixed the final failure but
   post-dates the last full run.
2. **#597 first among the follow-ups** — the two bulk batch queries still keep the newest
   mandate per membership, and they feed the same SEPA-XML fields. A per-member refusal
   there would be N queries where there is now 1; the ambiguity is already visible in their
   own result set, so count rows per membership and blank the ambiguous ones.
3. **#596 is bigger than it looks.** 15 dead `validate()` methods are 15 rules someone
   believed were being enforced. The triage question per site is not "delete or keep" but
   *"was this rule ever enforced anywhere else?"*
4. **Then #576** — `process_individual_return` swallows a deadlock into
   `{"status": "error"}` and reports success, on an unattended path.

And the one to carry forward from today: **before concluding a mechanism does not exist,
list the candidates you did not check.** I had one. It was in a docstring, in a test named
for the scenario, and it took CI 26 failures to make me read it.
