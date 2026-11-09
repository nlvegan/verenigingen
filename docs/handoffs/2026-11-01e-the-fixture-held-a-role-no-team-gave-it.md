# 2026-11-01e: the fixture held a role no team gave it

This continues session `ee`, after `2026-11-01c-a-rerun-of-the-old-head-cancelled-the-new-one.md` (PR #1955, merged). Read that note first. This one covers only what came after it. No agents are running.

## Maintainer rulings (recorded in `dispatch/author_brief_common.md` and on the issues)

- **Staff are registered through a staff TEAM** (an association-wide Team with default profile "Verenigingen Staff"; members are added to it). Staff are NOT made by assigning the Staff role or profile on the user. Tests that need a staff user must build one through a Team membership.
- **#1969:** a staffer who holds ANY chapter board seat (default, role-specific or financial) keeps Staff as a second profile AND gets the seat's board profile and roles. A default seat must add the board role too. This extends the #1615 national exception.

## Lessons

1. **A fix that adds behaviour to a shared write path needs EVERY test on that path run, not a sample.** #1922's new `after_insert` hook gave standalone board-row inserts the real profile sync. Author and reviewer each ran 3 of the ~14 modules that insert board rows that way, and CI reddened on a 4th (#1954, `test_dashboard_expense_scope_1701`). The sync is a REPLACE, so fixture users holding directly assigned roles lost them. Both briefs now carry this rule.
2. **A fixture that hand-assigns a role hides how production grants it.** Repairing #1954's tests by restoring the fixture's roles after the sync (`keep_fixture_roles`) was rejected. Building staff the production way (a real staff Team) exposed a real production defect instead: team-granted Staff was replaced by any board seat with priority above 75 (#1969, now fixed in #1974).
3. **GitHub's CONFLICTING flag can be stale.** #1932 and #1954 both showed "merge conflicts" and stopped automerge, yet `origin/develop` merged into each cleanly. Try the merge locally before resolving anything, then re-run the affected modules on the merged tree.
4. **A GitHub re-run reuses the original merge SHA.** After an upstream test fix lands, a re-run of a red PR tests the OLD tree. Use `gh pr update-branch <n>` instead (#1948, #1932).
5. **Order-dependence found in CI is usually not the PR's.** Neither #1948's red nor #1932's red came from its own code. #1948's came from a shared Membership Type "Regular" (#1071, fixed by #1966). #1932's came from a shared webhook rate-limit bucket ("unknown" IP; #1971, fixed by #1973). `scripts/testing/order_dependence_detector.py --modules <shard order> --json-out <f>` reproduces it in one process. Plain `bench run-tests` with several `--module` flags runs only the last one.
6. **Polling loops can exhaust the shared GitHub API quota** (5000/hr across all sessions). It happened once today. Poll every 3-5 minutes, and prefer one background watch that exits on an actionable event over repeated 30-minute monitors.

## Merged since the 01c note

#1942 (#1898), #1943 (#1909), #1944 (#1902), #1946 (#1894), #1948 (#1911), #1949 (#1853), #1951 (#1831), #1952 (#1899), #1955 (01c note), #1966 (#1071), #1973 (#1971), and the inherited #1913, #1887, #1862 and #1932 (#1860/#1908).

## Open at hand-off

- **#1954 (#1922)**, head 777b0dd7e: `origin/develop` merged in after a stale CONFLICTING flag, and 6 modules are green on test_site_3. A background job in ee's session queues it when CI is green. If that job is dead, queue it by hand.
- **#1974 (#1969)**, head 7a0751543: queued.
- **#1933** (ed's 2026-11-01 handoff note): still open. Queued together with this note.
- **veg11:** needs a final `bench --site veg11.veganisme.org migrate` once the queue drains. It was last migrated at bc68a0852.

## Filed this stretch

- #1938: `cancel_membership` leaves the dues schedule live.
- #1939: borrowed TestCase classes re-run.
- #1945: cleanup fallback sends no "left" mail.
- #1947: `has_permission` query-count residual.
- #1950: JS validator file arguments and false positives.
- #1953: standalone board-row deactivate and delete.
- #1969: Staff displaced by a seat. Fixed by #1974.
- #1971: limiter test pollution. Fixed by #1973.
- #1972: "unknown" IP bucket in production, not probed.

Earlier: #1934, #1935, #1936 (needs a ruling: should the self-service gate be `Member.user` only?) and #1937.

## Test sites

test_site_9 carries leaked rows from review runs, so treat it as dirty. Its `test_permissions_coverage` failure is site dirt; the module is green on test_site_3.
