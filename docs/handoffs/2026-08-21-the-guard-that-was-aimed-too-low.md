# Handoff — 2026-08-21: the guard that was aimed too low

Continuation of 2026-08-20b. That session fixed #201 and built a ratchet over the
application form's element ids. This one found that the ratchet was pointed at the wrong
half of the payload, that the half it could not see carried the payment method, and that
the tests written to prove the fix could not catch the fix being undone.

The recurring shape, three times in one session: **a guard that watches the instance you
already knew about.**

## Landed

| PR | | merge |
|---|---|---|
| #409 | skills reach the volunteer record; both wire vocabularies made canonical | `5b5ec383` |
| #413 | ratchet over the form's element ids, + two fields that were losing data | `166ba2a7` |

## Open

| PR | | state |
|---|---|---|
| #423 | Phase 0 — the applicant's payment choice never reached the payload | reviewed, 41 green, **shard 9 red on a pre-existing leak (#433)** |
| #432 | Phase 1 — remove the page that could never submit, + the link guard | reviewed before opening, CI running |
| #416 | handoff 2026-08-20b | open |

Spec: `docs/superpowers/specs/2026-08-20-application-form-consolidation-design.md`, on branch
`docs/application-form-consolidation-spec`. Six phases; 0 and 1 are the two PRs above.

## The defect that mattered: every application said Bank Transfer

`collectFormDataDirectly()` reads the payment radios correctly. `getAllFormData()` then
merges `getAdditionalFormData()` **second**, and that set `payment_method` from
`this.getPaymentMethod()`, which read only `this.paymentMethod || this.state.get(...)`.

Nothing on the page writes that state. Counted on the rendered page:

| selector | occurrences |
|---|---|
| `.payment-method-option` (state writer) | **0** |
| `.payment-method-radio` (state writer) | **0** |
| `name="payment_method"` (what renders) | 3 |

And state is pre-seeded: `get_application_form_data()` returns no `payment_methods` key, so
`loadPaymentMethods([])` falls to `showPaymentMethodFallback()`, which selects
`fallbackMethods[0]` — Bank Transfer, SEPA Direct Debit second.

**An applicant choosing SEPA Direct Debit got `Member.payment_method = "Bank Transfer"` and
never entered the mandate path**, while the radios are `required` so the choice looked
recorded. #420, fixed in #423.

The ratchet from #413 could not see it: it parsed `collectFormDataDirectly()` only, leaving
the two values that carry money — payment method and contribution amount — unguarded. Same
shape as the GL-query sibling in CLAUDE.md. The guard now parses both halves; all four of
the second function's id reads resolve, so the baseline did not grow.

## Three times the guard was aimed at the instance, not the class

1. **#413's ratchet** parsed one of the two payload builders. #420 lived in the other.
2. **#423's tests** exercised `getPaymentMethod` in isolation. With the helper left fixed
   and #420 reintroduced **verbatim in its caller**, all 680 jest tests and all 4 ratchet
   tests stayed green. A suite that cannot catch a verbatim reintroduction of its own
   defect is not a regression guard. Fixed by testing at caller altitude.
3. **#432's link guard** shipped reading one fixture. Its sibling in the same directory,
   `email_template.json`, sends members whose payment just failed to
   `/members/bank-details` — which 404s (#429).

**The lesson is not "write more guards", it is: name the artifact that has to be correct,
then check that the guard reads that artifact.** In all three cases the guard read what was
convenient to parse.

## Wrong things I published, and how

- **`Member.newsletter_opt_in` "is stored 0 on every member".** There is no such column.
  `DESCRIBE tabMember` — no `newsletter_opt_in`, no `application_source`, no
  `application_source_details`. The assignment at `application_helpers.py:686` is a silent
  no-op. I reached the claim by reading the assignment, published it in #412, #413 and a
  handoff, and corrected all three. `assigning-nonexistent-doc-field-is-silent-noop` was
  already in memory when I did it.
- **`payment_method` "works via a name fallback"** — written into the #413 ratchet baseline
  as its stated reason. The selector it named renders **0** times, and the value was being
  overwritten anyway. **A wrong explanation in a ratchet baseline is a search query nobody
  runs.**
- **A whitelisted endpoint, deleted by accident.** In #432 a line-index deletion ran two
  lines long and removed `@frappe.whitelist()` / `@public_api` from
  `get_membership_type_details`. Caught by review, confirmed against a develop control.

## Agent findings are leads, not facts

The reviews were run with `skeptical-code-reviewer` and found something real every time —
including a live defect while reviewing a *design document*. They were also confidently
wrong three times, in ways that would have gone into public issues as fact:

| claim | what checking showed |
|---|---|
| applicants are not gated on consent | they are — `required` plus a `name`-based validator at `membership_application.js:725`. The real defect is that acceptance is never *recorded* |
| the newsletter preference is lost | `#opt_out_optional_emails` → `accepts_optional_communications` captures it correctly |
| `uses_custom_amount` is false on every application, forever | `applyCalculatedAmount()` sets it; the accurate finding is that validation runs for income-calculator users only (#428) |

**Run the review before opening the PR** — Foppe had to ask twice — **and verify its findings
before repeating them.**

## Open issues from this session

| # | |
|---|---|
| #412 | the class: 12 payload fields still broken, each with the decision it needs |
| #410 | volunteer interests inert at both ends |
| #427 | `map_payment_method` silently records iDEAL and PayPal as Bank Transfer |
| #428 | custom-amount validation skipped unless the income calculator was used |
| #429 | dunning emails link members to a 404 |
| #430 | 23 backend methods called by six shipped pages do not exist or are not whitelisted |
| #433 | `test_calculate_cumulative_membership_duration` leaks a submitted Membership — **this is what reddens #423** |

## Facts worth not rediscovering

- **`enable_volunteer_signup = 0` on veg11**, `1` on test_site_1. The entire volunteering
  step is switched off live, so #201's fix is correct but dormant there — and the ratchet is
  green under a configuration production does not run. Under the live setting **16** fields
  break, not 12.
- **No member on veg11 came through either application form**: 748 members, **0** with
  `application_id`, **0** with `application_date`, **0** with `pronouns`. All from the CSV
  import. None of these defects has harmed a real applicant yet.
- `gh issue view` is broken here exactly like `gh pr edit` (Projects-classic GraphQL). Use
  `gh api repos/:owner/:repo/issues/N`.
- Rendering a page to count needles is the 60-second check that started all of this:
  `get_response_content('apply_for_membership')` as Guest, and **always count a control
  needle you know is present**.

## Not done

**veg11 is now running #409 and #413 — I did not deploy it.** The live site is served from
the working tree at `apps/verenigingen`, and `git pull` there *is* a deploy, so I
deliberately never ran one. But the tree moved during the session on its own: it read
`4cc0c502` early and `adae1ddf` by the end, and both merge commits are ancestors of that:

```
5b5ec383 IS in the live tree
166ba2a7 IS in the live tree
```

So the skills fix and the selector ratchet are live. **Do not assume the live tree is where
you last saw it** — check before reasoning about what is deployed:

```bash
git -C ~/frappe-bench/apps/verenigingen log --oneline -1
```

Practical consequence: the volunteering step is still switched off on veg11
(`enable_volunteer_signup = 0`), so the skills fix is deployed but dormant. #423 and #432 are
not merged, so **the payment-method defect is live on the deployed site**.

#423 cannot go green until #433 is fixed or its shard re-packs. Phases 2-5 of the spec are
unstarted; Phase 5 (migrate the collector to `FormData`) is blocked on Phase 0 landing.
