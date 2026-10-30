# 2026-10-30b: the fix closed it only at save

This session continued from `2026-10-30-the-yearly-slot-could-bill-monthly.md` (PR #1736). The
maintainer's instructions, in order:

1. Read the handoff. (It existed only on the remote branch of #1736, not in a local worktree;
   #1736 is still open.)
2. "look into the red shards" of #1727. Then: keep join reasons as a child table; consider whether
   Member loads too much.
3. "commit and push the fixes"; "start on the `_get_member_name` fix for #1743"; "yes" to its PR.
4. Re-run the flaky shard; "yes" to an independent review of #1727.
5. "please fix any issues that the review and CI run flag and then merge when green, write a
   handoff afterwards."

## Decisions made by the maintainer

| Subject | Decision |
|---|---|
| Join reasons on Member | **Keep the child table** (`join_reasons`, Table MultiSelect). Its cost is +1 select per Member load. |
| A separate application doctype | Raised as an idea. Not needed for performance: only child tables cost queries per load, and plain columns are free. The real lever is #1743 / #1748. |
| F2 (mail cap) | Fix it. I chose 3 mails per address per day (one constant). |

## What exists now

**PR #1727 (`/word-lid`): MERGED** as `a38a8e4d3` on 2026-10-30, pinned to the reviewed head
`86775c3c2`. CI was 55/55 green, and the push-only gates (`dispatch/premerge.sh`) were green on
develop `262476218`. The page is **not live on veg11 yet** (see Owed).

The red shards on the first CI run were both guard tests doing their job:
- The endpoint census pinned 50 `@handle_api_error` endpoints, and #1727 adds 2. Re-pinned to 52,
  with both names asserted.
- The chapter bulk-save query cap went from 270 to 290. The new child table costs +20 queries
  (10 members, each loaded twice), measured from CI's own query list.

The pre-merge review (two reviewers, then a delta reviewer) found five real defects. All are fixed
in `ffc78d3bd`, `03d65cd59` and `86775c3c2`; the PR body has the table. The two that matter:
- **Money:** the yearly-slot fix (I1) worked only when the door was saved. Editing the template's
  frequency afterwards still let approval bill a Monthly €7.50 choice as Annual €7.50.
- **Availability:** every anonymous visitor shared one 100/h rate-limit bucket, keyed `Guest`.

**PR #1753 (`_get_member_name`, #1743):** open, reviewed (APPROVE) and **CI-green (55/55), but not
merged:** the maintainer was not asked to merge it. It turns 9 queries into 1 per lookup; the
10-member chapter save goes from 273 to 193 queries on this bench. **Whichever of #1727 and #1753 merges second should tighten the bulk-save cap** in
`tests/chapter/test_chapter_members_integration.py` to the new CI floor, about 200. Not measured on
CI yet.

## Owed (in order)

1. #1753: merge (green), then tighten the bulk-save cap (above). It was branched before #1727, so
   re-check that CI is still green on the merge with develop first.
2. Browser smoke test of `/word-lid` (jest only so far; the Playwright MCP failed to connect again).
3. veg11 configuration after merge, from the previous handoff's step 3: pull, migrate, restart, the
   Huisgenoot and Student types, the three doors, and one Regulier submit → confirm → approve.
   **New:** once a door uses a template, the template's billing frequency cannot be changed (by
   design). Repoint the door first.
4. #1034 is now the big one. 57 guest endpoints sit on the shared Guest bucket, including the
   existing `submit_application` and the Mollie, ING and Ponto webhooks. Whether a webhook arrives
   as Guest is **not** verified. The test meant to catch this only prints a warning
   (`test_public_api_guest_access.py:954`).

## Rulings I made (the maintainer has not seen these individually)

- **Mail cap:** 3 per address per 24 h. Past it the call returns the same success and stores and
  sends nothing. Cost: 3 junk submits block a real applicant for 24 h with no signal.
- **Template-frequency guard** (in shared `Membership Dues Schedule` code): a frequency change is
  refused while a door slot (enabled or not) or a Pending / Under Review / Payment Pending
  application uses the template. Cost: staff must repoint a door, or settle a stale application,
  before changing a template's period. No code path saves such a change today (writer grep).
- **Lost savepoint:** a full `frappe.db.rollback()` before the re-raise. Cost: it also discards
  anything else uncommitted in that confirm request (COR audit rows at "minimal" level).
- **Honeypot** renamed to `leave_this_empty`, with the label "Laat dit veld leeg".
- **Card text** may not contain links or form controls, and intro text may not contain form
  controls. Inline `style` is still allowed (parked).
- **Not fixed, recorded in #1729:**
  - Approval has no frequency check of its own, so an import or `set_value` after confirm is
    still billed on the new period.
  - Some unasked reapplication fields are overwritten.
  - `style` and `<img>` survive in card and intro text.
  - Pre-I2 payloads are refused at confirm.

## Issues filed or updated this session

- Filed: #1742 (this bench counts about 5 more queries than CI), #1743 (Chapter save loads each
  Member in full twice), #1748 (266 `get_doc` loads to read 1–2 fields), #1758 (mail tests need an
  enabled outgoing Email Account; sites 1, 4, 5 and 13 have none).
- Updated: #1034 (measured repro plus the 57-endpoint census), #1578 (the timing flake: 4.4 s, then
  10.75 s, then 6.92 s on identical code), #1729 (the review round), #1166 (cross-link).

## What went right, and what nearly didn't

- **The fix round answering the last review had never been reviewed, and it held the money bug.**
  Each of the 11 commits fixed its finding, and the tests killed every mutant aimed at them. But I1
  was closed only at the moment the door is saved. Approval reads the template's period when it
  runs, days later. The repo lesson *review the round that answers the review* is what triggered
  the review. The mutants could not have found it: they all exercised door save.
- **Two of my own instruments lied, and in both cases a control caught it.**
  - `frappe.cache.delete_keys` adds the site prefix, but the rate-limit engine writes raw keys.
    So my cleanup, and the reviewer's, deleted nothing, and a later test started against an
    already-full bucket. I had also reported "remaining keys: 0".
  - A mutant run printed "OK" because MariaDB's safe-update mode refused the mutation itself.
  - Rule: check the mutation (or the cleanup) changed the state before trusting what follows.
- **My first reproduction of the shared bucket said "not reproduced".** `check_rate_limit` returns
  `allowed=False`; it does not raise. Inspecting the result object, not the absence of an
  exception, is what showed 102/100.
- **Shared test sites bit three times.** Another agent migrated test_site_9 with develop three
  minutes after I migrated it with the branch, which wiped the branch's DocTypes mid-measurement.
  test_site_10 and 13 had no usable outgoing Email Account (#1758). Record sites in
  `~/frappe-bench/dispatch/ledger.md` *before* using them; another coordinator was dispatching at
  the same time.
- **`premerge.sh` used one fixed worktree path and `--force`-removed it.** Running it while another
  session's `automerge.sh` ran could delete that session's tree. It now uses `.wt-premerge-$SHA`.
  I edited it in place (atomically, with nothing running it) and noted the change in the ledger.
- **I stated an unverified claim on an issue twice** (#1578: "the same shard passed last run";
  #1034: "#1727 adds per_ip rows" before it did). Both are corrected in place, but each was public
  for a few minutes.
