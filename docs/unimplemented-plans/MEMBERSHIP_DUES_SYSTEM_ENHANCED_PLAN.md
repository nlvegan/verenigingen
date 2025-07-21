# Membership Dues System - Enhanced Implementation Plan
*Updated to reflect flexible contribution system based on current UX patterns*

## Overview

This enhanced plan adapts the comprehensive membership dues system to support two different organizational approaches:

1. **Tier-Based Organizations**: Organizations that offer predefined contribution tiers (Student, Standard, Supporter, etc.)
2. **Calculator-Based Organizations**: Organizations that offer income-based contribution calculators with fractional multipliers

The system maintains the sophisticated SEPA integration and payment processing from V2 while providing the flexibility that different organizations need.

---

## 1. Flexible Contribution System Design

### 1.1 Enhanced Membership Type Configuration

```python
class MembershipType(Document):
    """
    Enhanced Membership Type supporting both tier-based and calculator-based organizations
    """
    # Existing fields...

    # Core Contribution Settings
    minimum_contribution: Currency = 5.00  # Hard minimum
    suggested_contribution: Currency = 15.00  # Base amount for calculations
    maximum_contribution: Currency = 0  # Optional maximum (0 = no limit)

    # Organization Type Selection
    contribution_mode: Select["Tiers", "Calculator", "Both"] = "Calculator"

    # Income Calculator Configuration
    enable_income_calculator: Check = 1
    income_percentage_rate: Float = 0.5  # 0.5% of monthly net income
    calculator_description: Text = "Our suggested contribution is 0.5% of your monthly net income"

    # Tier Configuration (Optional)
    predefined_tiers: Table[MembershipTier]

    # Member Choice Settings
    allow_custom_amounts: Check = 1
    custom_amount_requires_approval: Check = 0
    fee_slider_max_multiplier: Float = 10.0  # Maximum multiplier for slider

    def get_contribution_options(self):
        """Get contribution options based on organization configuration"""
        options = {
            "mode": self.contribution_mode,
            "minimum": self.minimum_contribution,
            "suggested": self.suggested_contribution,
            "maximum": self.maximum_contribution or (self.suggested_contribution * self.fee_slider_max_multiplier),
            "calculator": {
                "enabled": self.enable_income_calculator,
                "percentage": self.income_percentage_rate,
                "description": self.calculator_description
            }
        }

        if self.contribution_mode in ["Tiers", "Both"]:
            options["tiers"] = []
            for tier in self.predefined_tiers:
                options["tiers"].append({
                    "name": tier.tier_name,
                    "display_name": tier.display_name,
                    "amount": tier.amount,
                    "description": tier.description,
                    "requires_verification": tier.requires_verification,
                    "is_default": tier.is_default
                })

        if self.contribution_mode in ["Calculator", "Both"]:
            # Generate fractional multipliers for calculator-based organizations
            multipliers = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 5.0]
            options["quick_amounts"] = []
            for multiplier in multipliers:
                amount = self.suggested_contribution * multiplier
                if amount >= self.minimum_contribution:
                    options["quick_amounts"].append({
                        "multiplier": multiplier,
                        "amount": amount,
                        "label": f"{int(multiplier * 100)}%" if multiplier != 1.0 else "Suggested",
                        "is_default": multiplier == 1.0
                    })

        return options

class MembershipTier(Document):
    """
    Child table for predefined membership tiers
    """
    tier_name: Data  # "Student", "Standard", "Supporter"
    display_name: Data  # "Student Membership", "Standard Membership"
    amount: Currency
    description: Text
    requires_verification: Check = 0
    is_default: Check = 0
    display_order: Int = 0
```

### 1.2 Enhanced Member Portal Interface

```html
<!-- Flexible contribution selection matching current UX -->
<div class="contribution-selection-container">
    <h3>{{ _("Choose Your Contribution") }}</h3>

    <!-- Income Calculator (if enabled) -->
    {% if contribution_options.calculator.enabled %}
    <div class="income-calculator-card">
        <h5>{{ _("Contribution Calculator") }}</h5>
        <p>{{ contribution_options.calculator.description }}</p>

        <div class="calculator-inputs">
            <div class="input-group">
                <label for="calc-monthly-income">{{ _("Monthly Net Income (€)") }}</label>
                <input type="number" id="calc-monthly-income"
                       placeholder="3500" min="0" step="0.01">
            </div>

            <div class="input-group">
                <label for="calc-payment-interval">{{ _("Payment Interval") }}</label>
                <select id="calc-payment-interval">
                    <option value="monthly">{{ _("Monthly") }}</option>
                    <option value="quarterly">{{ _("Quarterly") }}</option>
                    <option value="annual">{{ _("Annual") }}</option>
                </select>
            </div>
        </div>

        <div class="calculator-result">
            <p>{{ _("Suggested contribution: ") }}<span id="calculated-amount">€0.00</span></p>
            <button type="button" id="use-calculated-amount" class="btn btn-outline">
                {{ _("Use This Amount") }}
            </button>
        </div>
    </div>
    {% endif %}

    <!-- Contribution Options -->
    {% if contribution_options.mode == "Tiers" %}
    <!-- Predefined Tiers -->
    <div class="contribution-tiers">
        {% for tier in contribution_options.tiers %}
        <div class="tier-card {{ 'default' if tier.is_default else '' }}">
            <h4>{{ tier.display_name }}</h4>
            <div class="tier-amount">€{{ tier.amount }}</div>
            <p>{{ tier.description }}</p>
            <button type="button" class="tier-select-btn"
                    data-amount="{{ tier.amount }}"
                    data-tier="{{ tier.name }}">
                {{ _("Select") }}
            </button>
        </div>
        {% endfor %}
    </div>
    {% else %}
    <!-- Quick Amount Selection (Calculator Mode) -->
    <div class="quick-amounts">
        <h5>{{ _("Quick Selection") }}</h5>
        <div class="amount-buttons">
            {% for amount in contribution_options.quick_amounts %}
            <button type="button" class="amount-btn {{ 'default' if amount.is_default else '' }}"
                    data-amount="{{ amount.amount }}"
                    data-multiplier="{{ amount.multiplier }}">
                <span class="amount-label">{{ amount.label }}</span>
                <span class="amount-value">€{{ amount.amount }}</span>
            </button>
            {% endfor %}
        </div>
    </div>
    {% endif %}

    <!-- Fee Slider (Always Available) -->
    <div class="fee-slider-container">
        <h5>{{ _("Custom Amount") }}</h5>
        <div class="slider-wrapper">
            <input type="range" id="fee-slider"
                   min="{{ contribution_options.minimum }}"
                   max="{{ contribution_options.maximum }}"
                   step="0.50"
                   value="{{ contribution_options.suggested }}">
        </div>

        <div class="fee-input-group">
            <label for="custom-amount">{{ _("Amount (€)") }}</label>
            <input type="number" id="custom-amount"
                   min="{{ contribution_options.minimum }}"
                   max="{{ contribution_options.maximum }}"
                   step="0.50"
                   value="{{ contribution_options.suggested }}">
        </div>

        <div class="fee-info">
            <p><small>{{ _("Minimum: €{0}").format(contribution_options.minimum) }}</small></p>
            <p><small>{{ _("Suggested: €{0}").format(contribution_options.suggested) }}</small></p>
        </div>
    </div>

    <!-- Selected Amount Display -->
    <div class="selected-amount-display">
        <h4>{{ _("Selected Contribution") }}</h4>
        <div class="amount-display">
            <span class="selected-amount">€<span id="selected-amount-value">{{ contribution_options.suggested }}</span></span>
            <span class="frequency">{{ _("per month") }}</span>
        </div>
    </div>
</div>
```

### 1.3 Enhanced JavaScript for Flexible UX

```javascript
class ContributionSelector {
    constructor(options) {
        this.options = options;
        this.selectedAmount = options.suggested;
        this.initialize();
    }

    initialize() {
        this.setupSlider();
        this.setupQuickAmounts();
        this.setupCalculator();
        this.setupTiers();
    }

    setupSlider() {
        const slider = document.getElementById('fee-slider');
        const input = document.getElementById('custom-amount');

        // Sync slider and input
        slider.addEventListener('input', (e) => {
            const value = parseFloat(e.target.value);
            input.value = value;
            this.updateSelectedAmount(value);
        });

        input.addEventListener('input', (e) => {
            const value = parseFloat(e.target.value);
            if (!isNaN(value)) {
                slider.value = value;
                this.updateSelectedAmount(value);
            }
        });
    }

    setupQuickAmounts() {
        const buttons = document.querySelectorAll('.amount-btn');
        buttons.forEach(button => {
            button.addEventListener('click', (e) => {
                const amount = parseFloat(e.target.dataset.amount);
                this.setAmount(amount);
                this.highlightButton(button);
            });
        });
    }

    setupCalculator() {
        if (!this.options.calculator.enabled) return;

        const incomeInput = document.getElementById('calc-monthly-income');
        const intervalSelect = document.getElementById('calc-payment-interval');
        const useCalculatedBtn = document.getElementById('use-calculated-amount');

        const calculate = () => {
            const income = parseFloat(incomeInput.value) || 0;
            const percentage = this.options.calculator.percentage;
            const baseAmount = income * (percentage / 100);

            // Adjust for interval
            const interval = intervalSelect.value;
            let calculatedAmount = baseAmount;

            if (interval === 'quarterly') {
                calculatedAmount = baseAmount * 3;
            } else if (interval === 'annual') {
                calculatedAmount = baseAmount * 12;
            }

            // Ensure minimum
            calculatedAmount = Math.max(calculatedAmount, this.options.minimum);

            document.getElementById('calculated-amount').textContent = `€${calculatedAmount.toFixed(2)}`;

            useCalculatedBtn.onclick = () => {
                this.setAmount(calculatedAmount);
            };
        };

        incomeInput.addEventListener('input', calculate);
        intervalSelect.addEventListener('change', calculate);
    }

    setupTiers() {
        const tierButtons = document.querySelectorAll('.tier-select-btn');
        tierButtons.forEach(button => {
            button.addEventListener('click', (e) => {
                const amount = parseFloat(e.target.dataset.amount);
                const tier = e.target.dataset.tier;
                this.setAmount(amount, tier);
                this.highlightTierCard(button.closest('.tier-card'));
            });
        });
    }

    setAmount(amount, tier = null) {
        this.selectedAmount = amount;
        this.selectedTier = tier;

        // Update all UI elements
        document.getElementById('fee-slider').value = amount;
        document.getElementById('custom-amount').value = amount;
        document.getElementById('selected-amount-value').textContent = amount.toFixed(2);

        // Clear other highlights
        this.clearHighlights();

        // Trigger change event
        this.onAmountChange(amount, tier);
    }

    updateSelectedAmount(amount) {
        this.selectedAmount = amount;
        document.getElementById('selected-amount-value').textContent = amount.toFixed(2);
        this.onAmountChange(amount);
    }

    onAmountChange(amount, tier = null) {
        // Override this method to handle amount changes
        console.log('Amount changed:', amount, 'Tier:', tier);
    }

    clearHighlights() {
        document.querySelectorAll('.amount-btn').forEach(btn => btn.classList.remove('selected'));
        document.querySelectorAll('.tier-card').forEach(card => card.classList.remove('selected'));
    }

    highlightButton(button) {
        this.clearHighlights();
        button.classList.add('selected');
    }

    highlightTierCard(card) {
        this.clearHighlights();
        card.classList.add('selected');
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    const contributionOptions = {{ contribution_options|tojson }};
    const selector = new ContributionSelector(contributionOptions);

    // Handle amount changes
    selector.onAmountChange = (amount, tier) => {
        // Update hidden form fields
        document.getElementById('membership_fee').value = amount;
        if (tier) {
            document.getElementById('membership_tier').value = tier;
        }

        // Update payment summary
        updatePaymentSummary(amount);
    };
});
```

---

## 2. Enhanced Data Model

### 2.1 Membership Dues Schedule Enhancement

```python
class MembershipDuesSchedule(Document):
    """
    Enhanced dues schedule supporting both tier and calculator modes
    """
    # Core Information
    member: Link[Member]
    membership: Link[Membership]
    membership_type: Link[MembershipType]

    # Contribution Selection
    contribution_mode: Select["Tier", "Calculator", "Custom"] = "Calculator"
    selected_tier: Link[MembershipTier]  # If tier-based
    base_multiplier: Float = 1.0  # If calculator-based

    # Amount Configuration
    amount: Currency
    minimum_amount: Currency  # From membership type
    suggested_amount: Currency  # From membership type

    # Custom Amount Handling
    uses_custom_amount: Check = 0
    custom_amount_reason: Text
    custom_amount_approved: Check = 0
    custom_amount_approved_by: Link[User]

    # SEPA Integration (from V2)
    payment_method: Select["SEPA Direct Debit", "Bank Transfer", "PSP"] = "SEPA Direct Debit"
    active_mandate: Link[SEPAMandate]
    next_sequence_type: Select["FRST", "RCUR"] = "FRST"

    # Billing Configuration
    billing_frequency: Select["Monthly", "Quarterly", "Annual"] = "Monthly"
    billing_day: Int  # Day of month for anniversary billing

    # Coverage Tracking
    current_coverage_start: Date
    current_coverage_end: Date
    next_invoice_date: Date

    # Status Management
    status: Select["Active", "Paused", "Grace Period", "Suspended"] = "Active"
    grace_period_until: Date
    last_payment_date: Date
    consecutive_failures: Int = 0

    def validate(self):
        self.validate_amount_configuration()
        self.set_billing_day()
        self.calculate_coverage_dates()

    def validate_amount_configuration(self):
        """Validate amount based on contribution mode"""
        membership_type = frappe.get_doc("Membership Type", self.membership_type)

        if self.contribution_mode == "Tier" and self.selected_tier:
            tier = frappe.get_doc("MembershipTier", self.selected_tier)
            self.amount = tier.amount
        elif self.contribution_mode == "Calculator":
            self.amount = membership_type.suggested_contribution * self.base_multiplier
        elif self.contribution_mode == "Custom":
            if not self.uses_custom_amount:
                frappe.throw("Custom amount must be enabled for custom contribution mode")

        # Validate against minimum
        if self.amount < membership_type.minimum_contribution:
            frappe.throw(f"Amount cannot be less than minimum: €{membership_type.minimum_contribution}")

    def set_billing_day(self):
        """Set billing day based on member's approval anniversary"""
        if not self.billing_day:
            member = frappe.get_doc("Member", self.member)
            if member.member_since:
                self.billing_day = getdate(member.member_since).day
            else:
                self.billing_day = 1

    def calculate_coverage_dates(self):
        """Calculate coverage periods for clear invoicing"""
        if not self.current_coverage_start:
            self.current_coverage_start = today()

        if self.billing_frequency == "Monthly":
            self.current_coverage_end = add_months(self.current_coverage_start, 1) - timedelta(days=1)
            self.next_invoice_date = add_months(self.current_coverage_start, 1)
        elif self.billing_frequency == "Quarterly":
            self.current_coverage_end = add_months(self.current_coverage_start, 3) - timedelta(days=1)
            self.next_invoice_date = add_months(self.current_coverage_start, 3)
        elif self.billing_frequency == "Annual":
            self.current_coverage_end = add_months(self.current_coverage_start, 12) - timedelta(days=1)
            self.next_invoice_date = add_months(self.current_coverage_start, 12)
```

---

## 3. Application Process Enhancement

### 3.1 Payment-First Application with Flexible Contribution

```python
def process_membership_application_enhanced(application_data):
    """
    Enhanced application process supporting both tier and calculator modes
    """
    # 1. Create application record
    application = frappe.new_doc("Membership Application")
    application.update(application_data)

    # 2. Process contribution selection
    membership_type = frappe.get_doc("Membership Type", application.membership_type)

    if application.contribution_mode == "Tier" and application.selected_tier:
        tier = frappe.get_doc("MembershipTier", application.selected_tier)
        application.first_payment_amount = tier.amount
        application.contribution_description = f"{tier.display_name} - €{tier.amount}"
    elif application.contribution_mode == "Calculator":
        base_amount = membership_type.suggested_contribution
        multiplier = application.base_multiplier or 1.0
        application.first_payment_amount = base_amount * multiplier
        application.contribution_description = f"{int(multiplier * 100)}% of suggested amount - €{application.first_payment_amount}"
    else:
        # Custom amount
        application.first_payment_amount = application.custom_amount
        application.contribution_description = f"Custom amount - €{application.custom_amount}"

    # 3. Validate minimum amount
    if application.first_payment_amount < membership_type.minimum_contribution:
        frappe.throw(f"Amount cannot be less than minimum: €{membership_type.minimum_contribution}")

    # 4. Create SEPA mandate if provided
    if application.sepa_mandate_consent:
        mandate = create_pending_sepa_mandate(application)
        application.sepa_mandate = mandate.name

    # 5. Create invoice with clear coverage period
    invoice = create_application_invoice_with_coverage(application)
    application.first_invoice = invoice.name

    # 6. Process first payment
    payment_request = create_application_payment_request(application, invoice)

    return {
        "application": application.name,
        "invoice": invoice.name,
        "payment_request": payment_request,
        "contribution_summary": application.contribution_description,
        "next_step": "complete_payment"
    }
```

---

## 4. Member Experience Enhancements

### 4.1 Enhanced Member Dashboard

```html
<!-- Member dashboard showing flexible contribution info -->
<div class="member-contribution-dashboard">
    <div class="contribution-summary-card">
        <h3>{{ _("Your Membership Contribution") }}</h3>

        <div class="current-contribution">
            <div class="contribution-amount">
                <span class="amount">€{{ current_dues.amount }}</span>
                <span class="frequency">{{ _("per {0}").format(current_dues.billing_frequency.lower()) }}</span>
            </div>

            <div class="contribution-details">
                {% if current_dues.contribution_mode == "Tier" %}
                <p><strong>{{ _("Tier") }}:</strong> {{ current_dues.selected_tier_name }}</p>
                {% elif current_dues.contribution_mode == "Calculator" %}
                <p><strong>{{ _("Amount") }}:</strong> {{ (current_dues.base_multiplier * 100)|int }}% of suggested</p>
                {% else %}
                <p><strong>{{ _("Custom Amount") }}:</strong> {{ current_dues.custom_amount_reason }}</p>
                {% endif %}
            </div>
        </div>

        <div class="contribution-actions">
            <button class="btn btn-outline" onclick="showContributionAdjustment()">
                {{ _("Adjust Contribution") }}
            </button>
        </div>
    </div>

    <!-- Payment Status -->
    <div class="payment-status-card">
        <h4>{{ _("Payment Status") }}</h4>
        <div class="status-indicator status-{{ payment_status }}">
            <i class="fa fa-{{ payment_status_icon }}"></i>
            <span>{{ payment_status_text }}</span>
        </div>

        <div class="payment-details">
            <p><strong>{{ _("Coverage Period") }}:</strong> {{ current_dues.current_coverage_start }} - {{ current_dues.current_coverage_end }}</p>
            <p><strong>{{ _("Next Payment") }}:</strong> {{ current_dues.next_invoice_date }}</p>
            <p><strong>{{ _("Payment Method") }}:</strong> {{ current_dues.payment_method }}</p>
        </div>
    </div>
</div>
```

---

## 5. Implementation Phases

### Phase 1: Core Infrastructure (Month 1)
- Enhanced MembershipType with flexible contribution options
- Updated MembershipDuesSchedule with contribution tracking
- Basic member portal interface for contribution selection

### Phase 2: Application Integration (Month 2)
- Payment-first application flow with contribution selection
- SEPA mandate integration
- Invoice generation with coverage periods

### Phase 3: Advanced Features (Month 3)
- Income calculator functionality
- Contribution adjustment workflows
- Enhanced member dashboard

### Phase 4: SEPA Enhancement (Month 4)
- Enhanced batch processing with proper FRST/RCUR tracking
- Payment failure handling
- Administrative interfaces

### Phase 5: Testing & Deployment (Month 5)
- Comprehensive testing with both tier and calculator modes
- Data migration from existing systems
- User training and documentation

---

## 6. Configuration Examples

### Example 1: Tier-Based Organization
```python
# Membership Type Configuration
membership_type = {
    "name": "Standard Membership",
    "minimum_contribution": 5.00,
    "suggested_contribution": 15.00,
    "contribution_mode": "Tiers",
    "enable_income_calculator": 0,
    "predefined_tiers": [
        {"tier_name": "Student", "amount": 8.00, "requires_verification": 1},
        {"tier_name": "Standard", "amount": 15.00, "is_default": 1},
        {"tier_name": "Supporter", "amount": 25.00}
    ]
}
```

### Example 2: Calculator-Based Organization
```python
# Membership Type Configuration
membership_type = {
    "name": "Income-Based Membership",
    "minimum_contribution": 5.00,
    "suggested_contribution": 15.00,
    "contribution_mode": "Calculator",
    "enable_income_calculator": 1,
    "income_percentage_rate": 0.5,
    "calculator_description": "We suggest 0.5% of your monthly net income",
    "fee_slider_max_multiplier": 10.0
}
```

This enhanced plan provides the flexibility needed for both organizational approaches while maintaining the sophisticated SEPA integration and payment processing capabilities.
