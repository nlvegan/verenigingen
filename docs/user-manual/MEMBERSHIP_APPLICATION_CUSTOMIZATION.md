# Membership Application Form Customization Guide

## Overview

The membership application form in Verenigingen uses a **Page Template** approach, which provides complete control over styling, branding, and user experience. This guide explains how to customize the form's appearance and add organizational branding.

## Understanding Web Forms vs Page Templates

### Web Forms
- **Purpose**: Quick database-driven forms
- **Setup**: Point-and-click configuration
- **Styling**: Limited to Frappe's default styling
- **Use case**: Simple forms that map directly to a DocType

### Page Templates (Used by Membership Application)
- **Purpose**: Custom HTML pages with full design control
- **Setup**: Requires HTML/CSS/JavaScript coding
- **Styling**: Complete control over appearance and user experience
- **Use case**: Complex workflows, custom branding, multi-step processes

**The membership application uses a Page Template** because it provides:
- Multi-step wizard interface
- Custom progress indicators
- Organizational branding capabilities
- Responsive design control

## File Structure

The membership application consists of these key files:

```
verenigingen/
├── templates/pages/
│   └── apply_for_membership.html          # Main template file
├── public/
│   ├── css/
│   │   └── membership_application.css     # Custom styling
│   ├── images/
│   │   └── logo.png                       # Organization logo
│   └── js/
│       └── membership_application.js      # Custom JavaScript
```

## Adding Organization Logo

### Step 1: Add Logo File

1. **Create images directory** (if it doesn't exist):
   ```bash
   mkdir -p /home/frappe/frappe-bench/apps/verenigingen/verenigingen/public/images
   ```

2. **Copy your logo file**:
   ```bash
   # For PNG logo
   cp /path/to/your/logo.png /home/frappe/frappe-bench/apps/verenigingen/verenigingen/public/images/logo.png

   # For other formats
   cp /path/to/your/logo.jpg /home/frappe/frappe-bench/apps/verenigingen/verenigingen/public/images/logo.jpg
   cp /path/to/your/logo.svg /home/frappe/frappe-bench/apps/verenigingen/verenigingen/public/images/logo.svg
   ```

### Step 2: Update Template

The template is already configured to display a logo. If you use a different filename or format, update the image source in `apply_for_membership.html`:

```html
<div class="organization-logo mb-3">
    <img src="/assets/verenigingen/images/logo.png" alt="Organization Logo" class="logo-img">
</div>
```

### Step 3: Rebuild Assets

After adding files, rebuild the assets:
```bash
bench build --app verenigingen
```

## Customizing Styling

### CSS File Location

Custom styles are defined in:
```
/home/frappe/frappe-bench/apps/verenigingen/verenigingen/public/css/membership_application.css
```

### Key Styling Classes

```css
/* Main container */
.membership-application-form {
    max-width: 800px;
    margin: 0 auto;
    padding: 20px;
}

/* Logo styling */
.organization-logo .logo-img {
    max-height: 80px;
    max-width: 200px;
    height: auto;
    width: auto;
}

/* Header section */
.page-header {
    border-bottom: 2px solid #e9ecef;
    padding-bottom: 20px;
    margin-bottom: 30px;
}

/* Progress indicators */
.progress-container {
    background: #f8f9fa;
    padding: 20px;
    border-radius: 8px;
    border: 1px solid #dee2e6;
}

/* Form cards */
.card {
    border: none;
    box-shadow: 0 0.125rem 0.25rem rgba(0, 0, 0, 0.075);
    border-radius: 8px;
}
```

### Brand Color Customization

To match your organization's brand colors, modify these CSS variables:

```css
/* Primary brand color */
.btn-primary {
    background-color: #your-primary-color;
    border-color: #your-primary-color;
}

/* Progress indicator color */
.progress-steps .step.active {
    color: #your-accent-color;
}

/* Header text color */
.page-header h1 {
    color: #your-heading-color;
}
```

### Logo Size Adjustment

Adjust logo dimensions in the CSS:

```css
.organization-logo .logo-img {
    max-height: 100px;        /* Increase for larger logo */
    max-width: 250px;         /* Adjust width */
    height: auto;             /* Maintain aspect ratio */
    width: auto;              /* Maintain aspect ratio */
}
```

## Responsive Design

The form includes responsive design for mobile devices:

```css
@media (max-width: 768px) {
    .membership-application-form {
        padding: 15px;
    }

    .organization-logo .logo-img {
        max-height: 60px;     /* Smaller logo on mobile */
        max-width: 150px;
    }

    .progress-steps {
        flex-direction: column; /* Stack progress steps */
        text-align: center;
    }
}
```

## Advanced Customization Options

### 1. Custom Fonts

Add custom fonts by importing them in the CSS file:

```css
@import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600&display=swap');

.membership-application-form {
    font-family: 'Open Sans', sans-serif;
}
```

### 2. Background Patterns

Add subtle background patterns:

```css
.membership-application-form {
    background-image: url('/assets/verenigingen/images/pattern.png');
    background-repeat: repeat;
    background-size: 50px 50px;
}
```

### 3. Custom Animations

Enhance user experience with smooth transitions:

```css
.form-step {
    animation: fadeIn 0.3s ease-in;
}

@keyframes fadeIn {
    from {
        opacity: 0;
        transform: translateY(10px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}
```

### 4. Logo Placement Variations

#### Header with Logo and Navigation
```html
<div class="page-header">
    <div class="header-top d-flex justify-content-between align-items-center">
        <img src="/assets/verenigingen/images/logo.png" alt="Logo" class="header-logo">
        <nav class="header-nav">
            <a href="/">Home</a>
            <a href="/about">About</a>
        </nav>
    </div>
    <div class="header-content text-center">
        <h1>{{ _("Become a Member") }}</h1>
        <p class="lead">{{ _("Join our association!") }}</p>
    </div>
</div>
```

#### Logo as Background Watermark
```css
.membership-application-form::before {
    content: '';
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    background-image: url('/assets/verenigingen/images/logo.png');
    background-size: 200px;
    background-repeat: no-repeat;
    opacity: 0.05;
    z-index: -1;
}
```

## Template Structure Overview

The `apply_for_membership.html` template includes:

### 1. CSS Block
```html
{% block style %}
<link href="/assets/verenigingen/css/membership_application.css" rel="stylesheet">
{% endblock %}
```

### 2. Header Section
```html
<div class="page-header text-center">
    <div class="organization-logo mb-3">
        <img src="/assets/verenigingen/images/logo.png" alt="Organization Logo" class="logo-img">
    </div>
    <h1>{{ _("Become a Member") }}</h1>
    <p class="lead">{{ _("Join our association and become part of our community!") }}</p>
</div>
```

### 3. Progress Indicator
```html
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
```

### 4. Multi-Step Form
```html
<form id="membership-application-form" class="application-form">
    <div class="form-step active" data-step="1">
        <!-- Step 1 content -->
    </div>
    <div class="form-step" data-step="2">
        <!-- Step 2 content -->
    </div>
    <!-- ... more steps ... -->
</form>
```

## Deployment Checklist

After making customizations:

1. **Test logo file accessibility**:
   - Visit: `https://yoursite.com/assets/verenigingen/images/logo.png`
   - Should display your logo

2. **Test CSS loading**:
   - Check browser developer tools for any 404 errors
   - Verify styles are applied correctly

3. **Test responsive design**:
   - Check form on desktop, tablet, and mobile
   - Verify logo scales appropriately

4. **Rebuild assets**:
   ```bash
   bench build --app verenigingen
   ```

5. **Clear browser cache**:
   - Force refresh with `Ctrl+F5` (or `Cmd+Shift+R` on Mac)

## Troubleshooting

### Logo Not Displaying
- **Check file path**: Ensure logo exists at the specified path
- **Check file permissions**: Logo file should be readable
- **Rebuild assets**: Run `bench build --app verenigingen`
- **Clear cache**: Hard refresh browser

### Styles Not Applied
- **Check CSS file path**: Verify CSS file exists in `/public/css/`
- **Check for syntax errors**: Validate CSS syntax
- **Check browser console**: Look for 404 errors
- **Rebuild assets**: Run `bench build --app verenigingen`

### Mobile Layout Issues
- **Test viewport meta tag**: Should be in base template
- **Check media queries**: Verify responsive CSS rules
- **Test on actual devices**: Emulator may not reflect real behavior

## Best Practices

### Performance
- **Optimize images**: Compress logo files for web
- **Minimize CSS**: Remove unused styles
- **Use appropriate image formats**: SVG for logos, PNG for photos

### Accessibility
- **Alt text**: Always include descriptive alt text for images
- **Color contrast**: Ensure sufficient contrast for text readability
- **Keyboard navigation**: Test form navigation with Tab key

### Maintainability
- **Document changes**: Comment complex CSS rules
- **Use semantic class names**: Make CSS classes descriptive
- **Separate concerns**: Keep styling in CSS files, not inline

## Version Control

When making customizations:

1. **Backup original files** before making changes
2. **Document all modifications** in comments
3. **Test thoroughly** before deploying to production
4. **Consider upgrade impact**: Custom changes may need updates when upgrading Frappe

## Advanced Integration

### Dynamic Logo Based on Settings

You can make the logo configurable through settings:

```python
# In apply_for_membership.py
def get_context(context):
    settings = frappe.get_single('Verenigingen Settings')
    context.organization_logo = settings.get('organization_logo', '/assets/verenigingen/images/logo.png')
    context.organization_name = settings.get('organization_name', 'Verenigingen')
```

```html
<!-- In template -->
<img src="{{ organization_logo }}" alt="{{ organization_name }} Logo" class="logo-img">
```

This approach allows administrators to change the logo through the settings interface without modifying code.
