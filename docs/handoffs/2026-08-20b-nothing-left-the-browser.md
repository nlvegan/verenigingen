# Handoff — 2026-08-20b: nothing left the browser

Session goal was "start work on an open issue". #201 was picked off the list: *every skill
submitted through the public application form is stored as `Unknown`*. The report named a
key mismatch between the form JavaScript and the Volunteer controller.

The report was wrong about the mechanism, and being wrong about it was the whole finding.
Nothing ever left the browser, so the `Unknown` fallback the issue described was never
reached. Chasing that down turned one bug into a class of thirteen more, and the session
ended with a standing gate over the class rather than a second one-off fix.

## Landed

| PR | | merge |
|---|---|---|
| #409 | skills reach the volunteer record; both wire vocabularies made canonical | `5b5ec383` |
| #413 | ratchet over the form's element ids, + two fields that were losing data | `166ba2a7` |

#201 closed. **#412** and **#410** opened and left open on purpose (below).

## The diagnosis the issue got wrong

`getVolunteerSkills()` collected `.skill-row` / `input[name="skill_name[]"]`.
`apply_for_membership.html` renders neither. Rendering the page and counting needles —
with controls, because a sweep that returns zero for everything is a broken sweep:

| needle | occurrences in 350KB of HTML |
|---|---|
| `skill-row` | **0** |
| `add-skill` | **0** |
| `skill_name[]` | **0** |
| `name="volunteer_skills[]"` | 31 |
| `id="volunteer_skill_level"` | 1 |
| `id="skills-selection"` (control) | 1 |
| `name="volunteer_areas[]"` (control) | 4 |

So the collector returned `[]` on every submission, `volunteer_skills` was always falsy,
`member.volunteer_skills` was never set, and every volunteer was created with **no skills
at all**. The `.skill-row` machinery that misled the reporter is dead in both directions:
`addSkillRow()` appends after `$('.skill-row').last()`, an empty set on every page, and
its `.add-skill` trigger exists in no template in `apps/`.

**The check that settled this took sixty seconds** and is worth reaching for by reflex:

```bash
cd ~/frappe-bench/sites && ../env/bin/python -c "
import frappe; frappe.init(site='test_site_1'); frappe.connect()
from frappe.website.serve import get_response_content
frappe.set_user('Guest')
html = get_response_content('apply_for_membership')
print(html.count('skill-row'), html.count('name=\"volunteer_skills[]\"'))"
```

## Two vocabularies were wrong on the same wire value

Fixing transport alone would have filed every skill under `Other` at `1 - Beginner`, which
is what the issue *thought* was already happening:

- the checkbox carried `category.name` — the **translated** heading (`Technical Skills`, or
  Dutch on a Dutch site) where `Volunteer Skill.skill_category` declares `Technical`.
  Display name and stored option are now separate keys.
- the proficiency select offered `1`..`5` where the field declares `1 - Beginner`..
  `5 - Expert`. Option values are canonical now; the labels keep their explanatory text.

**A translated Jinja string must never become a Select wire value.** `coerce_select_option`
is exact-match, so the fallback swallows the mismatch without an error — the same silent
shape as #341.

## What the skeptical review caught, and where it was wrong

The review was run only after the PR was already open, which was the wrong order.

It found two real defects in the fix:

1. **The category fix was a no-op on any site that configures its own categories.**
   `Volunteer Skill Category.category_name` is free text, and this app's own defaults use
   the longer form, so an admin mirroring them into settings filed everything under
   `Other` — exactly what the commit message claimed had been made impossible. Now coerced
   at the source. Both this bench and veg11 have **0** such rows, so it was latent.
2. **`enhanced_test_factory` was a third divergent shape** for the same payload: raw
   `"Technical|Web Development"` wire strings, which take the `isinstance(skill, str)`
   branch and are stored as a skill of that whole name under `Other` — the #201 symptom
   baked into a fixture — plus a `"1".."5"` level the PR had just retired. Fixed in **both**
   copies of that duplicated helper.

It also correctly flagged that the commit claimed the tests "bind the payload at both ends
of the wire". They do not: each end is pinned to the same literal key set and nothing
compares them. Claim retracted rather than machinery built to justify it.

**Two of its findings did not survive checking**, and both mattered:

- It framed the consent gap as applicants not being gated. They are: the boxes carry
  `required` and the live validator at `membership_application.js:725` checks
  `input[name="terms_accepted"]`. The real defect is that acceptance is transmitted as
  `false` and read by **no** server code — a missing record, not an open door.
- It said the newsletter preference is lost. The page captures it via
  `#opt_out_optional_emails`, which *is* read correctly.

Agent findings are leads. Both of these would have gone into a public issue as fact.

## The class, and the gate over it (#412 / #413)

The review's best contribution was insisting #201 was one instance. `collectFormDataDirectly()`
builds the **entire payload** `submit_application` receives by reading element ids out of the
page. Of its **31 payload fields that read an id, 14 resolve to nothing** on the rendered
page — measured by the guard itself, not estimated:

| field | reads | page renders | effect |
|---|---|---|---|
| `contact_number` | `#contact_number` | `id="mobile_no"` | every applicant's phone number stored empty |
| `additional_notes` | `#additional_notes` | `id="volunteer_comments"` | the motivation text never reached `Member.notes` |
| `newsletter_opt_in` | `#newsletter_opt_in` | nothing | **nothing is stored** — see correction below |
| `terms`, `gdpr_consent`, `confirm_accuracy` | those ids | `name="terms_accepted"` / `name="privacy_accepted"`, no ids | consent never recorded |
| 7 more | — | nothing | always `''` |

`contact_number` and `additional_notes` are fixed in #413 (fallback chains, because
`#contact_number` **is** rendered by three other templates — picking one would fix this page
by breaking those). The other twelve stay in the baseline, each with the decision it needs
written next to it.

**`verenigingen/tests/backend/portal/test_application_form_selector_contract.py`** is the
gate. Keyed per *payload field*, not per id, because several read a fallback chain and are
only broken when none resolve. It fails in four directions, each verified by mutation:

| mutation | result |
|---|---|
| broken field not in baseline | `['additional_notes', 'contact_number'] != []`, ids named |
| working field added to baseline | "these fields now resolve; delete them from…" |
| invented field in baseline | "names payload fields collectFormDataDirectly() no longer has…" |
| collector renamed | one-line message — **the control** |

That fourth one is not decoration. Without it a parser returning `{}` makes every other
assertion vacuously true, which is precisely the failure this file exists to prevent. Its
first version used `str.index`, which raised with **300KB of JavaScript** in the report.

## The correction I had to publish afterwards

I wrote — here, in #412, and in #413's description — that `newsletter_opt_in` means "every
member is stored `0`, defeating `data.get("newsletter_opt_in", 1)`". Both halves false.
`DESCRIBE tabMember` says:

```
tabMember.newsletter_opt_in           ** NO COLUMN **
tabMember.application_source          ** NO COLUMN **
tabMember.application_source_details  ** NO COLUMN **
tabMember.accepts_optional_communications  EXISTS
```

So `member.newsletter_opt_in = ...` at `application_helpers.py:686` is a **silent no-op**
and nothing is stored either way. `transfer_iban` / `transfer_account_name` are likewise not
"always empty" but read **nowhere** server-side.

I reached the false version by reading the assignment rather than asking the database —
the same class of mistake this session had just finished documenting, made while writing it
up. `assigning-nonexistent-doc-field-is-silent-noop` was already in memory. **Reading an
assignment tells you what the author intended; only the schema tells you what happens.**

## Traps worth carrying forward

- **`tests/frontend/setup.js` stubs `global.$` as a jest.fn returning stubs, and jquery is
  not in `node_modules`.** Any jQuery-mediated jsdom assertion is stub-defeated by
  construction. The three collector tests here *do* go red on develop, but with
  `TypeError: $(...).each is not a function` — a real red for an environmental reason.
  Writing the collector in vanilla `querySelectorAll` is what made a real DOM test possible.
- **A hand-copied markup fixture agrees only with itself.** The jest file reads the actual
  template with `fs.readFileSync`; renaming the checkbox in the template turns it red.
- **`gh issue view` is broken here exactly like `gh pr edit`** — Projects-classic GraphQL.
  Use `gh api repos/:owner/:repo/issues/N`.
- `test_volunteer_skills_array_format` sat `@unittest.skip("needs investigation")` asserting
  a contract that never existed — wrong keys, plus an `"Advanced"` → `"4 - Advanced"` mapping
  nothing performs. A skipped test asserting a fiction is worse than no test; it reads as
  coverage. Replaced.

## Open, and what each needs

- **#412** — the twelve remaining fields. The three consent fields (should acceptance be
  persisted on `Member`?), seven fields with no control on the page, and `payment_method`
  (works via a `name`-based fallback). Plus the identical wrong ids at
  `membership_application.js:~4003` in the `BaseStep` subclasses — dead today because
  `StepManager` is never loaded, and **not** covered by the ratchet.
- **#410** — volunteer *interests* are inert at both ends: the JS addresses
  `#volunteer-interests` (0 occurrences on the page, which renders `volunteer_areas[]`) and
  `data["volunteer_interests"]` is read nowhere server-side. Needs a decision on where an
  applicant's areas of interest would be stored before any code moves.

## Not done, on purpose

**veg11 was not deployed.** The live site is served straight out of the working tree at
`apps/verenigingen`, which is still at `4cc0c502`; `git pull` there *is* a deploy and was
not asked for. Applicants are still submitting through the old form until someone pulls.

Also unaddressed: draft resumption on this page has never worked. `hooks/assets.py:29` ships
only `operation-result-helpers.js` in `web_include_js` and the template's sole
`frappe.require` loads `membership_application.js`, so `StorageService` is undefined and
`saveDraft()` / `loadExistingDraft()` are inert. Same missing-wiring root as the dead
`BaseStep` copies. Not filed.
