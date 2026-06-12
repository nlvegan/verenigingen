# Payment Dashboard Contextual Dues-Adjustment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dues rate adjustment action easy to find on the member payment dashboard by placing it contextually next to the rate display, instead of a standalone card that drowns among other cards.

**Architecture:** Single Jinja template change in `verenigingen/templates/pages/payment_dashboard.html`. The standalone "Adjust Dues Rate" card between the metric cards and the tab block is removed; the action moves into the Current Schedule Details panel (Overview tab, visible on load) and as an inline link next to "Current rate" in the SEPA card (Payment Methods tab). Passive metric cards lose their hover lift so they no longer fake interactivity, and dead `.quick-action*` CSS is deleted.

**Tech Stack:** Frappe Jinja portal template, Tailwind utility classes, existing `btn-primary` portal class. No Python or JS changes.

**Spec:** `docs/superpowers/specs/2026-06-12-payment-dashboard-dues-adjust-visibility-design.md`

**Verification approach:** There is no automated test coverage for this template's markup. Each task verifies via `grep` and a Jinja syntax parse check; pre-commit runs the template field validator on the HTML file at commit time. Final visual check happens on a rendered page (Foppe verifies on the live dashboard after deploy).

**Line numbers** below refer to the file BEFORE any task is executed; use the quoted code (not the numbers) to locate edits — earlier tasks shift later line numbers.

---

### Task 1: Move the action into Current Schedule Details, remove the standalone card

**Files:**
- Modify: `verenigingen/templates/pages/payment_dashboard.html` (card at ~450–466, schedule panel at ~525–556)

- [ ] **Step 1: Add the adjust button to the Current Schedule Details panel**

In the Overview tab's Current Schedule Details gray panel, find the Next Invoice Date row (the last row in the `bg-gray-50` panel):

```html
                                <div class="flex justify-between">
                                    <span class="text-sm text-gray-600">{{ _("Next Invoice Date") }}</span>
                                    <span class="text-sm font-medium">
                                        {% if current_schedule.next_invoice_date %}
                                            {{ frappe.format_value(current_schedule.next_invoice_date, {"fieldtype": "Date"}) }}
                                        {% else %}
                                            -
                                        {% endif %}
                                    </span>
                                </div>
                            </div>
```

Replace with (adds a bordered footer action inside the panel, mirroring the existing "Set Up Schedule" button styling in the no-schedule fallback):

```html
                                <div class="flex justify-between">
                                    <span class="text-sm text-gray-600">{{ _("Next Invoice Date") }}</span>
                                    <span class="text-sm font-medium">
                                        {% if current_schedule.next_invoice_date %}
                                            {{ frappe.format_value(current_schedule.next_invoice_date, {"fieldtype": "Date"}) }}
                                        {% else %}
                                            -
                                        {% endif %}
                                    </span>
                                </div>
                                <div class="pt-3 border-t border-gray-200 text-center">
                                    <a href="/membership_adjustment" class="btn-primary text-sm">
                                        {{ _("Adjust dues rate") }} &rarr;
                                    </a>
                                </div>
                            </div>
```

- [ ] **Step 2: Remove the standalone quick-action card**

Delete this entire block (between the three metric cards and the `<!-- Tabs -->` block):

```html
        <!-- Quick Action -->
        <div class="mb-8 flex justify-center">
            <a href="/membership_adjustment" class="group block max-w-md w-full bg-white border-2 border-primary-300 rounded-xl p-5 hover:border-primary-500 hover:shadow-lg hover:shadow-primary-100 transition-all duration-200 text-decoration-none">
                <div class="flex items-center gap-4">
                    <div class="flex-shrink-0 w-14 h-14 bg-primary-100 rounded-xl flex items-center justify-center group-hover:bg-primary-200 transition-colors">
                        <i class="fa fa-sliders-h text-primary-600 text-xl"></i>
                    </div>
                    <div class="flex-1">
                        <div class="font-semibold text-gray-900 text-lg">{{ _("Adjust Dues Rate") }}</div>
                        <div class="text-sm text-gray-600">{{ _("Modify your contribution amount") }}</div>
                    </div>
                    <div class="flex-shrink-0 text-primary-500 group-hover:translate-x-1 transition-transform">
                        <i class="fa fa-chevron-right"></i>
                    </div>
                </div>
            </a>
        </div>

```

(Leave the `<!-- Tabs -->` block that follows untouched.)

- [ ] **Step 3: Verify the move with grep**

Run:
```bash
grep -n "membership_adjustment\|Adjust Dues Rate\|Adjust dues rate" verenigingen/templates/pages/payment_dashboard.html
```
Expected: exactly 3 matched lines — the new button's `href="/membership_adjustment"` line, its `{{ _("Adjust dues rate") }}` label line (the label sits on its own line), and the existing "Set Up Schedule" fallback's href line. No "Adjust Dues Rate" (capital D/R, the removed card's label) should match. Also run:
```bash
grep -c "fa-sliders-h" verenigingen/templates/pages/payment_dashboard.html
```
Expected: `0`.

- [ ] **Step 4: Jinja syntax parse check**

Run:
```bash
python -c "
import jinja2
env = jinja2.Environment()
src = open('verenigingen/templates/pages/payment_dashboard.html').read()
env.parse(src)
print('PARSE OK')
"
```
Expected: `PARSE OK` (catches unbalanced tags/blocks; runtime names like `frappe.*` are not resolved at parse time).

- [ ] **Step 5: Commit**

```bash
git add verenigingen/templates/pages/payment_dashboard.html
git commit -m "feat(payment-dashboard): move dues-adjust action into schedule details panel"
```
Pre-commit's template field validator runs on the HTML file; expected to pass.

---

### Task 2: Inline "Adjust" link next to "Current rate" in the SEPA card

**Files:**
- Modify: `verenigingen/templates/pages/payment_dashboard.html` (SEPA setup block, ~line 671 pre-Task-1)

- [ ] **Step 1: Add the inline link**

In the SEPA Direct Debit card (Payment Methods tab), find:

```html
                                {% if active_dues_schedule %}
                                <p class="text-sm text-gray-600 mt-3">
                                    {% set frequency_map = {"Monthly": "month", "Quarterly": "quarter", "Yearly": "year", "Weekly": "week"} %}
                                    {% set frequency = frequency_map.get(active_dues_schedule.billing_frequency, active_dues_schedule.billing_frequency|lower) %}
                                    {{ _("Current rate") }}: <strong>{{ frappe.format_value(active_dues_schedule.amount, {"fieldtype": "Currency"}) }}</strong> {{ _("per") }} {{ frequency }}
                                </p>
                                {% endif %}
```

Replace with (text link, not a button — the card's own CTA "Set up automatic payment" stays dominant):

```html
                                {% if active_dues_schedule %}
                                <p class="text-sm text-gray-600 mt-3">
                                    {% set frequency_map = {"Monthly": "month", "Quarterly": "quarter", "Yearly": "year", "Weekly": "week"} %}
                                    {% set frequency = frequency_map.get(active_dues_schedule.billing_frequency, active_dues_schedule.billing_frequency|lower) %}
                                    {{ _("Current rate") }}: <strong>{{ frappe.format_value(active_dues_schedule.amount, {"fieldtype": "Currency"}) }}</strong> {{ _("per") }} {{ frequency }}
                                    <a href="/membership_adjustment" class="text-primary-600 hover:text-primary-700 font-medium ml-1">{{ _("Adjust") }}</a>
                                </p>
                                {% endif %}
```

- [ ] **Step 2: Verify with grep**

Run:
```bash
grep -c "membership_adjustment" verenigingen/templates/pages/payment_dashboard.html
```
Expected: `3` (schedule-panel button from Task 1, SEPA inline link, no-schedule fallback).

- [ ] **Step 3: Jinja syntax parse check**

Same command as Task 1 Step 4. Expected: `PARSE OK`.

- [ ] **Step 4: Commit**

```bash
git add verenigingen/templates/pages/payment_dashboard.html
git commit -m "feat(payment-dashboard): add inline dues-adjust link next to current rate in SEPA card"
```

---

### Task 3: Calm passive cards and delete dead CSS

**Files:**
- Modify: `verenigingen/templates/pages/payment_dashboard.html` (style block: hover rule ~20–23, quick-action rules ~172–216, media query ~275–277)

- [ ] **Step 1: Remove the hover lift from `.financial-card`**

Find:

```css
.financial-card {
    background: white;
    border-radius: 1rem;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    border: 1px solid #e5e7eb;
    border-top: 4px solid #e5e7eb;
    transition: all 0.3s ease;
}

.financial-card:hover {
    box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
    transform: translateY(-2px);
}
```

Replace with (the `transition` only served the removed hover, so it goes too):

```css
.financial-card {
    background: white;
    border-radius: 1rem;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    border: 1px solid #e5e7eb;
    border-top: 4px solid #e5e7eb;
}
```

- [ ] **Step 2: Delete the dead `.quick-action*` rules**

Delete this entire block (no HTML uses these classes — verified during design):

```css
/* Quick Actions */
.quick-actions {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: 1rem;
}

.quick-action {
    background: white;
    border-radius: 0.75rem;
    padding: 1rem;
    border: 1px solid #e5e7eb;
    cursor: pointer;
    transition: all 0.2s ease;
    text-decoration: none;
    color: inherit;
}

.quick-action:hover {
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    transform: translateY(-1px);
    text-decoration: none;
    color: inherit;
}

.quick-action-icon {
    width: 2.5rem;
    height: 2.5rem;
    border-radius: 0.5rem;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 0.75rem;
}

.quick-action-title {
    font-weight: 600;
    color: #1f2937;
    margin-bottom: 0.25rem;
}

.quick-action-description {
    font-size: 0.875rem;
    color: #6b7280;
}

```

- [ ] **Step 3: Delete the `.quick-actions` rule from the mobile media query**

Inside `@media (max-width: 768px)`, delete:

```css

    .quick-actions {
        grid-template-columns: 1fr;
    }
```

Leave the other rules in the media query (`.financial-card`, `.tab-button`, `.metric-value`) untouched.

- [ ] **Step 4: Verify with grep**

Run:
```bash
grep -c "quick-action" verenigingen/templates/pages/payment_dashboard.html
grep -c "financial-card:hover" verenigingen/templates/pages/payment_dashboard.html
```
Expected: `0` and `0`.

- [ ] **Step 5: Jinja syntax parse check**

Same command as Task 1 Step 4. Expected: `PARSE OK`.

- [ ] **Step 6: Commit**

```bash
git add verenigingen/templates/pages/payment_dashboard.html
git commit -m "style(payment-dashboard): drop fake hover affordance on metric cards, delete dead quick-action CSS"
```

---

### Task 4: Final whole-file verification

**Files:** none modified.

- [ ] **Step 1: Confirm all spec requirements landed**

Run:
```bash
grep -n "membership_adjustment\|quick-action\|fa-sliders-h\|financial-card:hover" verenigingen/templates/pages/payment_dashboard.html
```
Expected output: exactly 3 lines, all `membership_adjustment` hrefs (schedule-panel button, SEPA inline link, no-schedule fallback). No `quick-action`, `fa-sliders-h`, or `financial-card:hover` matches.

- [ ] **Step 2: Confirm no JS references the removed card**

Run:
```bash
grep -rn "sliders-h\|Adjust Dues Rate" verenigingen/public/js/ verenigingen/templates/pages/payment_dashboard.html
```
Expected: no matches (the removed card had no id or event handlers; this confirms nothing else referenced it).

- [ ] **Step 3: Visual check (manual, deferred to Foppe)**

Foppe verifies on the rendered dashboard: with an active schedule the button shows at the bottom of Current Schedule Details; the SEPA card (no mandate) shows the inline "Adjust" link after the current rate; the standalone card is gone; metric cards no longer lift on hover; the no-schedule fallback is unchanged. Do NOT test against veg11 with write operations — this is a read-only page view.
