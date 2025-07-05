# Page Template Customization - Developer Guide

## Overview

This guide explains the technical implementation of Page Template customization in the Verenigingen app, using the membership application form as a primary example.

## Page Template Architecture

### File Structure

```
verenigingen/
├── templates/
│   └── pages/
│       ├── apply_for_membership.html      # Main template
│       ├── apply_for_membership.py        # Python controller
│       └── personal_details.html          # Other custom pages
├── public/
│   ├── css/
│   │   ├── membership_application.css     # Page-specific styles
│   │   └── verenigingen_custom.css        # Global custom styles
│   ├── js/
│   │   └── membership_application.js      # Page-specific JavaScript
│   └── images/
│       └── logo.png                       # Static assets
```

### Template Inheritance

Page templates extend Frappe's base web template:

```html
{% extends "templates/web.html" %}

{% block title %}{{ _("Apply for Membership") }}{% endblock %}

{% block style %}
<!-- Custom CSS -->
{% endblock %}

{% block page_content %}
<!-- Page content -->
{% endblock %}

{% block script %}
<!-- Custom JavaScript -->
{% endblock %}
```

## Implementation Details

### 1. Template File (`apply_for_membership.html`)

**Key Components:**

```html
<!-- CSS Block for Custom Styling -->
{% block style %}
<link href="/assets/verenigingen/css/membership_application.css" rel="stylesheet">
{% endblock %}

<!-- Main Content Block -->
{% block page_content %}
<div class="membership-application-form">
    <!-- Organization branding -->
    <div class="page-header text-center">
        <div class="organization-logo mb-3">
            <img src="/assets/verenigingen/images/logo.png" alt="Organization Logo" class="logo-img">
        </div>
        <h1>{{ _("Become a Member") }}</h1>
        <p class="lead">{{ _("Join our association and become part of our community!") }}</p>
    </div>

    <!-- Progress indicator -->
    <div class="progress-container mb-4">
        <div class="progress">
            <div class="progress-bar" role="progressbar" style="width: 16.67%" id="form-progress"></div>
        </div>
        <div class="progress-steps">
            <span class="step active" data-step="1">Personal Info</span>
            <span class="step" data-step="2">Address</span>
            <!-- ... more steps ... -->
        </div>
    </div>

    <!-- Multi-step form -->
    <form id="membership-application-form" class="application-form" onsubmit="return false;">
        <!-- Form steps -->
    </form>
</div>
{% endblock %}
```

### 2. Python Controller (`apply_for_membership.py`)

```python
import frappe
from frappe import _

def get_context(context):
    """
    Context processor for the membership application page
    """
    # Basic page setup
    context.no_cache = True
    context.show_sidebar = False

    # Organization settings
    settings = frappe.get_single('Verenigingen Settings')
    context.organization_name = settings.get('organization_name', 'Verenigingen')
    context.default_currency = frappe.get_cached_value("Company", settings.get('default_company'), "default_currency")

    # Membership types for dropdown
    context.membership_types = frappe.get_all('Membership Type',
        filters={'disabled': 0},
        fields=['name', 'membership_type', 'amount', 'description']
    )

    # Countries for address dropdown
    context.countries = frappe.get_all('Country', fields=['name', 'country_name'])

    # Check if user is logged in
    if frappe.session.user != 'Guest':
        # Pre-fill form with user data if available
        user_data = get_user_data()
        context.update(user_data)

    return context

def get_user_data():
    """Get existing user data to pre-fill form"""
    user = frappe.get_doc('User', frappe.session.user)

    # Check if user already has a member record
    member = frappe.db.get_value('Member', {'user': frappe.session.user}, '*', as_dict=True)

    return {
        'user_email': user.email,
        'user_first_name': user.first_name,
        'user_last_name': user.last_name,
        'existing_member': member
    }

@frappe.whitelist(allow_guest=True)
def submit_application(data):
    """
    Handle form submission
    """
    try:
        # Validate required fields
        validate_application_data(data)

        # Create member application record
        application = create_member_application(data)

        # Send confirmation email
        send_application_confirmation(application)

        return {
            'success': True,
            'application_id': application.name,
            'message': _('Application submitted successfully')
        }

    except Exception as e:
        frappe.log_error(f"Membership application error: {str(e)}")
        return {
            'success': False,
            'message': _('An error occurred while processing your application')
        }

def validate_application_data(data):
    """Validate form data"""
    required_fields = ['first_name', 'last_name', 'email', 'membership_type']

    for field in required_fields:
        if not data.get(field):
            frappe.throw(_('Field {0} is required').format(field))

    # Email validation
    import re
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, data.get('email')):
        frappe.throw(_('Invalid email address'))

def create_member_application(data):
    """Create member application record"""
    application = frappe.new_doc('Member Application')
    application.update(data)
    application.status = 'Pending Review'
    application.insert(ignore_permissions=True)
    return application
```

### 3. CSS Organization (`membership_application.css`)

**Design System Approach:**

```css
/* CSS Variables for Brand Consistency */
:root {
    --primary-color: #007bff;
    --secondary-color: #6c757d;
    --success-color: #28a745;
    --danger-color: #dc3545;
    --warning-color: #ffc107;
    --info-color: #17a2b8;

    --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    --border-radius: 0.375rem;
    --box-shadow: 0 0.125rem 0.25rem rgba(0, 0, 0, 0.075);
    --transition: all 0.15s ease-in-out;
}

/* Component-based styling */
.membership-application-form {
    /* Container styles */
}

.organization-logo {
    /* Logo container */
}

.progress-container {
    /* Progress indicator */
}

.form-step {
    /* Individual form steps */
}

.card {
    /* Form section cards */
}

/* Responsive breakpoints */
@media (max-width: 1200px) { /* Large devices */ }
@media (max-width: 992px) { /* Medium devices */ }
@media (max-width: 768px) { /* Small devices */ }
@media (max-width: 576px) { /* Extra small devices */ }
```

### 4. JavaScript Enhancement (`membership_application.js`)

```javascript
class MembershipApplicationForm {
    constructor() {
        this.currentStep = 1;
        this.totalSteps = 6;
        this.formData = {};

        this.init();
    }

    init() {
        this.bindEvents();
        this.setupValidation();
        this.loadSavedData();
    }

    bindEvents() {
        // Navigation buttons
        $(document).on('click', '.btn-next', (e) => this.nextStep(e));
        $(document).on('click', '.btn-prev', (e) => this.prevStep(e));

        // Form submission
        $(document).on('click', '.btn-submit', (e) => this.submitForm(e));

        // Auto-save functionality
        $(document).on('input', '.form-control', (e) => this.autoSave(e));
    }

    setupValidation() {
        // Real-time validation
        $('.form-control').on('blur', function() {
            $(this).closest('.form-group').find('.invalid-feedback').hide();

            if (this.checkValidity()) {
                $(this).removeClass('is-invalid').addClass('is-valid');
            } else {
                $(this).removeClass('is-valid').addClass('is-invalid');
                $(this).closest('.form-group').find('.invalid-feedback').show();
            }
        });
    }

    nextStep(e) {
        e.preventDefault();

        if (this.validateCurrentStep()) {
            if (this.currentStep < this.totalSteps) {
                this.currentStep++;
                this.updateStep();
            }
        }
    }

    prevStep(e) {
        e.preventDefault();

        if (this.currentStep > 1) {
            this.currentStep--;
            this.updateStep();
        }
    }

    updateStep() {
        // Hide all steps
        $('.form-step').removeClass('active');
        $('.progress-steps .step').removeClass('active');

        // Show current step
        $(`.form-step[data-step="${this.currentStep}"]`).addClass('active');
        $(`.progress-steps .step[data-step="${this.currentStep}"]`).addClass('active');

        // Update progress bar
        const progress = (this.currentStep / this.totalSteps) * 100;
        $('.progress-bar').css('width', `${progress}%`);

        // Scroll to top
        $('.membership-application-form').get(0).scrollIntoView({
            behavior: 'smooth'
        });
    }

    validateCurrentStep() {
        const currentStepElement = $(`.form-step[data-step="${this.currentStep}"]`);
        const requiredFields = currentStepElement.find('[required]');
        let isValid = true;

        requiredFields.each(function() {
            if (!this.checkValidity()) {
                $(this).addClass('is-invalid');
                isValid = false;
            } else {
                $(this).removeClass('is-invalid').addClass('is-valid');
            }
        });

        return isValid;
    }

    autoSave(e) {
        const field = e.target;
        this.formData[field.name] = field.value;

        // Save to localStorage
        localStorage.setItem('membership_application_draft', JSON.stringify(this.formData));
    }

    loadSavedData() {
        const savedData = localStorage.getItem('membership_application_draft');
        if (savedData) {
            this.formData = JSON.parse(savedData);

            // Populate form fields
            Object.keys(this.formData).forEach(fieldName => {
                const field = document.querySelector(`[name="${fieldName}"]`);
                if (field) {
                    field.value = this.formData[fieldName];
                }
            });
        }
    }

    async submitForm(e) {
        e.preventDefault();

        // Validate all steps
        let allValid = true;
        for (let step = 1; step <= this.totalSteps; step++) {
            this.currentStep = step;
            if (!this.validateCurrentStep()) {
                allValid = false;
                break;
            }
        }

        if (!allValid) {
            frappe.msgprint('Please fill all required fields');
            return;
        }

        // Collect form data
        const formData = new FormData(document.getElementById('membership-application-form'));
        const data = Object.fromEntries(formData.entries());

        try {
            // Show loading
            $('.btn-submit').prop('disabled', true).text('Submitting...');

            // Submit application
            const response = await frappe.call({
                method: 'verenigingen.templates.pages.apply_for_membership.submit_application',
                args: { data: data }
            });

            if (response.message.success) {
                // Clear saved data
                localStorage.removeItem('membership_application_draft');

                // Show success message
                this.showSuccessMessage(response.message.application_id);
            } else {
                frappe.msgprint(response.message.message);
            }

        } catch (error) {
            console.error('Submission error:', error);
            frappe.msgprint('An error occurred while submitting your application');
        } finally {
            $('.btn-submit').prop('disabled', false).text('Submit Application');
        }
    }

    showSuccessMessage(applicationId) {
        const successHtml = `
            <div class="alert alert-success text-center">
                <h4>Application Submitted Successfully!</h4>
                <p>Your application ID is: <strong>${applicationId}</strong></p>
                <p>You will receive a confirmation email shortly.</p>
                <a href="/" class="btn btn-primary">Return to Home</a>
            </div>
        `;

        $('.membership-application-form').html(successHtml);
    }
}

// Initialize when page loads
$(document).ready(function() {
    new MembershipApplicationForm();
});
```

## Asset Management

### CSS Processing
- **Location**: `/public/css/membership_application.css`
- **Processing**: Linked via `bench build` command
- **URL**: `/assets/verenigingen/css/membership_application.css`

### Image Assets
- **Location**: `/public/images/`
- **Processing**: Automatically linked by Frappe
- **URL**: `/assets/verenigingen/images/filename.ext`

### JavaScript Processing
- **Location**: `/public/js/membership_application.js`
- **Processing**: Linked via template or hooks.py
- **URL**: `/assets/verenigingen/js/membership_application.js`

## Build Process

### Asset Linking
```bash
# Link assets
bench build --app verenigingen

# Development watch mode
bench watch --app verenigingen
```

### Template Compilation
- Templates are automatically compiled by Frappe
- Changes take effect immediately (no restart required)
- Jinja2 template engine processes variables and logic

## Testing Strategy

### 1. Unit Testing (Python)
```python
# test_apply_for_membership.py
import unittest
import frappe
from verenigingen.templates.pages.apply_for_membership import submit_application

class TestMembershipApplication(unittest.TestCase):

    def setUp(self):
        # Create test data
        pass

    def test_valid_application_submission(self):
        data = {
            'first_name': 'Test',
            'last_name': 'User',
            'email': 'test@example.com',
            'membership_type': 'Regular'
        }

        result = submit_application(data)
        self.assertTrue(result['success'])

    def test_invalid_email_validation(self):
        data = {
            'first_name': 'Test',
            'last_name': 'User',
            'email': 'invalid-email',
            'membership_type': 'Regular'
        }

        with self.assertRaises(frappe.ValidationError):
            submit_application(data)
```

### 2. Frontend Testing (JavaScript)
```javascript
// test_membership_form.js
describe('Membership Application Form', function() {

    beforeEach(function() {
        // Set up DOM
        document.body.innerHTML = '<div id="test-container"></div>';
    });

    it('should validate required fields', function() {
        const form = new MembershipApplicationForm();

        // Test validation logic
        expect(form.validateCurrentStep()).toBe(false);
    });

    it('should progress through steps', function() {
        const form = new MembershipApplicationForm();

        form.nextStep();
        expect(form.currentStep).toBe(2);
    });
});
```

### 3. Integration Testing
```python
# Test complete workflow
def test_membership_application_workflow():
    # Submit application
    # Verify database record
    # Check email sending
    # Test admin review process
```

## Performance Optimization

### 1. CSS Optimization
- **Minimize unused styles**
- **Use CSS variables for consistency**
- **Optimize for critical rendering path**

### 2. JavaScript Optimization
- **Lazy load non-critical functionality**
- **Debounce auto-save operations**
- **Use efficient DOM queries**

### 3. Image Optimization
- **Compress images appropriately**
- **Use responsive image techniques**
- **Consider WebP format for modern browsers**

## Security Considerations

### 1. Input Validation
- **Server-side validation is mandatory**
- **Client-side validation is UX enhancement only**
- **Sanitize all user inputs**

### 2. CSRF Protection
- **Frappe automatically handles CSRF tokens**
- **Use `@frappe.whitelist()` decorator appropriately**

### 3. Permission Checks
- **Validate user permissions in Python controllers**
- **Don't rely on client-side permission checks**

## Deployment Checklist

1. **Test all form steps**
2. **Verify responsive design**
3. **Test form submission**
4. **Check email functionality**
5. **Validate error handling**
6. **Performance testing**
7. **Security audit**
8. **Accessibility compliance**

## Troubleshooting Guide

### Common Issues

**CSS not loading:**
- Check file path and permissions
- Rebuild assets: `bench build --app verenigingen`
- Clear browser cache

**JavaScript errors:**
- Check browser console for errors
- Verify jQuery is loaded
- Check for variable naming conflicts

**Form submission fails:**
- Check Python method whitelisting
- Verify field validation
- Check server logs for errors

**Images not displaying:**
- Verify file exists in `/public/images/`
- Check image path in template
- Rebuild assets

### Debug Tools

**Python debugging:**
```python
# Add to Python methods
frappe.log_error(f"Debug: {variable_name}")
print(f"Debug output: {data}")
```

**JavaScript debugging:**
```javascript
// Add to JavaScript
console.log('Debug:', variable);
frappe.msgprint('Debug message');
```

**Template debugging:**
```html
<!-- Add to template -->
{{ frappe.utils.pretty_date(frappe.utils.now()) }}
```

This comprehensive guide covers the technical implementation details for customizing Page Templates in the Verenigingen app, providing developers with the knowledge needed to create sophisticated, branded user experiences.
