# Setup Scripts

Setup and configuration scripts for system initialization and feature setup.

## Available Scripts

- **`setup_member_portal_home.py`** - Set up member portal home page configuration
- **`add_chapter_tracking_fields.py`** - Add chapter tracking fields to the system

## Usage

```bash
# Set up member portal home page
python scripts/setup/setup_member_portal_home.py

# Add chapter tracking fields
python scripts/setup/add_chapter_tracking_fields.py
```

## Purpose

Setup scripts are used for:

- Initial system configuration
- Feature initialization
- Adding new fields or functionality
- Configuring default settings

## Adding Setup Scripts

When adding new setup scripts:

1. Include clear documentation of what is being set up
2. Make scripts idempotent (safe to run multiple times)
3. Include validation to check if setup is already complete
4. Provide clear success/failure messages
5. Document any prerequisites or dependencies
