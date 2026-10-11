# 2026-10-11b: the JSON was not the source of truth

This session started from the 2026-09-28c handoff. That was the newest one committed to develop. The
2026-10-11 handoff was still an open PR (#1620), and I found it only later, in the ledger. The
maintainer's instructions, in order:

1. "please read the most recent committed handoff and see what open tasks there are";
2. "let's go with the permission setup issues, eg why are there docperm rows for a role we own?";
3. "are there any other similar issues? CBM's should be able to approve membership applications for
   their chapter. not sure what 'submit memebrship' would be, the doctype isn't submittable. go ahead
   with all 4.";
4. "sync, migrate veg11 and restart it";
5. "what's a frozen doctype?", then "might as well" (file the revocation limit as an issue);
6. "generate a handoff please".

Staffing:

- Two sonnet authors: #1588/#1589 on test_site_1, and #1621/#1622 on test_site_2.
- Two sonnet `skeptical-code-reviewer`s: test_site_8 and test_site_7.
- The coordinator checked each post-review delta itself, on test_site_3. Both were then merged with
  `automerge.sh`.

## Decisions made by the maintainer

| Subject | Decision | Where recorded |
|---|---|---|
| #1588 | Delete `setup_`/`reset_chapter_board_permissions` and the rest of the dead service. Do not repair them: the JSON is the source of truth for a role and a DocType we own. | #1588 comment, PR #1624 |
| Chapter Board Member on Membership | CBMs must be able to approve membership applications for their chapter. The JSON's `submit: 1` stays. | #1588 comment |
| Scope | All four: #1588, #1589, #1621 and #1622 | ledger |
| veg11 | Sync, migrate and restart | ledger |
| Revocation limit | File it | #1629 |

**Correction given to the maintainer.** Membership **is** submittable (`membership.json:174`).
`membership_creation_service.py:405-406` inserts the Membership and then submits it as the session user,
so the CBM `submit` grant is what makes chapter approval work. The dead service's `submit: 0` would
have broken approval if it had ever run.

## What was found: the JSON stops applying once a DocType has any `Custom DocPerm` row

The maintainer asked why there were DocPerm rows for a role we own. The answer turned out wider than
the two issues. If a DocType has even one `Custom DocPerm` row, Frappe uses only those rows and ignores
its JSON permissions (`frappe/model/meta.py:640-653`). Three things put rows there:

1. **The fixture `fixtures/custom_docperm.json`** (#1622). It shipped 38 rows for 11 core DocTypes as a
   raw import, which does not copy the stock rows first. Measured on test_site_1 and test_site_5:
   - Company, Account and Mode of Payment were left with only Employee Self Service and Verenigingen
     Webhook User.
   - Customer was left with only three roles.

   veg11 had complete sets, because its stock rows had been copied over before the fixture rows
   arrived.
2. **The HRMS Employee Self Service User Type** (#1621). Our custom Link fields on Expense Claim point
   at Chapter, Team, Volunteer and Expense Category. `UserType.add_select_perm_doctypes` grants the
   ESS role `select` on each of them, through `add_permission`, which runs `copy_perms` first. That
   froze all four DocTypes on veg11 at 2026-09-25 23:31.
3. **Our own `public_document_creator_setup.py`**, which deliberately calls `add_permission` on Member,
   Donor and Donation. It has not run on veg11.

"Frozen" is the session's word for case 2 and case 3: the full set of rows has been copied into
`Custom DocPerm`, so later JSON changes stop reaching that site. The maintainer asked what it means,
so the term needs explaining wherever it is used.

**Not a defect, and fast to settle by reading Frappe:** permission rows are OR'd per ptype
(`frappe/permissions.py:327`). So a narrower duplicate row grants nothing. #1589 needed no product
decision, despite what its "Suggested direction" said.

## What shipped

| PR | Closes | Merge | What |
|---|---|---|---|
| #1624 | #1588, #1589 | `debd00ca3` | Removed the narrower duplicate `Verenigingen Staff` row from Membership, Membership Type and Contribution Amendment Request. Those were all the duplicates in 142 own DocType JSONs. Added a test that forbids duplicate (role, permlevel, if_owner) rows. Deleted the dead service and its shim, its whitelist, fixture and baseline entries, and only the tests that called it. Added JSON controls for the CBM grants. Added patch `v2_2.remove_dead_chapter_board_permission_critical_operation_rules`, which deletes the 2 stale COR rows on existing sites. |
| #1625 | #1621, #1622 | `708e63ee5` | Retired the Custom DocPerm fixture. New `setup/custom_docperm_setup.py::apply_custom_permissions` runs on `after_install` and `after_migrate`. It repairs truncated core sets, but only when every role in the set is ours or a User Type role. It applies 37 core grants additively through `add_permission`. It reconciles frozen own DocTypes to their JSON, keeping undeclared rows such as the ESS `select` row and the public-creator grants. |

## Review rounds

| PR | Review finding | Disposition |
|---|---|---|
| #1624 | Removing rows from the COR fixture does not prune sites that already imported them | Fixed by the patch above. The test seeds both dead rules plus a live control. |
| #1624 | `error_swallow_baseline.txt` carries 2 stale lines on develop (pre-existing) | Filed as #1623 |
| #1625 F1 | The "grants lower flags" and "grants never raise" mutants survived, with 9/9 tests green | Added a test that seeds an existing row through `add_permission`. All three mutants now redden. |
| #1625 F2 | A duplicate key in the JSON makes the reconcile last-wins | Closed by #1624's de-duplication and its guard test |
| #1625 F3 | The `DocType` grant was inert, because meta skips custom perms for DocType | Removed, which brings the grants to 37 |
| #1625 F4/F5 | 6 stale references to the deleted fixture, and a dead test branch | Fixed |
| #1625 F6 | A failure aborts install or migrate | Kept on purpose, so it is not swallowed |

## Coordinator notes

- **The "most recent committed handoff" was not the most recent handoff.** I opened by reporting that
  veg11 had been running stale code since the 09-28c handoff. The ledger showed the 10-11 session had
  restarted it, and I corrected myself. Read the ledger's tail, not only `docs/handoffs/` on develop.
  Handoff PRs stay open for a long time.
- **Another quota death.** The org spend limit killed both authors in round 2.
  - The #1588 author had an uncommitted patch and test. I saved its diff plus a tarball of the
    untracked files to the scratchpad, and nothing was lost. The #1621 author was clean.
  - It also killed the #1588 reviewer, which had already delivered its report.
  - Both authors were resumed after the reset.
- **An author's "it hung" was a timeout.** `python -m unittest discover -s scripts/validation/tests`
  takes about 7m20s (697 tests, measured). That is longer than the tool's default 120s timeout. Give it
  a 600000 ms timeout and close stdin.
- **Test-site state.** The new reconcile and the fixed JSON now live in the DB of test_site_1, 2, 7
  and 8. The authors' `reload-doctype` and the reviewers' committed `apply_custom_permissions` runs put
  them there. This is post-fix state, not dirt. But those sites no longer show the pre-fix truncation.
  `reset_test_sites.sh` restores them; the maintainer runs it.

## Filed this session

- #1621, #1622: both fixed.
- #1623: `error_swallow_baseline.txt` drift on develop. Filed by the #1588 author.
- #1629: a permission revoked in an own DocType's JSON never reaches a frozen site. The reconcile is
  additive by key, because a leftover row cannot be told apart from an admin, ESS or public-creator
  row. It lists three directions and picks none.

## Final state

- **Merged:** #1624 → `debd00ca3`, #1625 → `708e63ee5`. Both had fully green CI and passed the
  `premerge.sh` gates. Both were merged pinned to the head commit.
- **Closed by merge:** #1588, #1589, #1621, #1622.
- **veg11:**
  - The tree is on develop `708e63ee5`, clean.
  - Backup `20261012_000306` (database 910 MiB) taken before migrate.
  - `migrate` OK:
    - the new patch is in Patch Log;
    - one Staff row each on the three de-duplicated DocTypes;
    - 0 dead COR rows;
    - the Custom DocPerm counts on Customer, Company, Account, Mode of Payment, Chapter, Team,
      Volunteer, Expense Category and DocType are unchanged, so the new step was a no-op there, as
      predicted.
  - `supervisorctl restart` OK at 00:08; `ping` returns `pong`.
- **Agents:** none running.
- **Worktrees:** this session's issue worktrees are removed and their branches deleted. The
  coordinator's detached check tree is removed. `handoff-1011b` holds this handoff.
- **Stash stack:** its 2 old entries, untouched.
- **Open for the maintainer:**
  - merge this handoff PR, and the earlier ones (#1448, #1527, #1538, #1556, #1581, #1620);
  - #1629: pick a direction, or accept the limit;
  - still open from earlier handoffs: #1596 and #1574 rulings, #1598 close, #1612 (a)/(b);
  - optionally `reset_test_sites.sh` for test_site_1, 2, 7 and 8.
