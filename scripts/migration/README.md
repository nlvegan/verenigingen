# Migration Scripts

Data migration and structure update scripts.

## Available Scripts

- **`migrate_amendment_data.py`** - Migrate amendment data to new structure
- **`migration_commands.py`** - General migration command utilities
- **`fix_team_assignment_history.py`** - Fix team assignment history data
- **`manual_employee_creation.py`** - Manually create employee records for existing volunteers

## Usage

```bash
# Migrate amendment data
python scripts/migration/migrate_amendment_data.py

# Fix team assignment history
python scripts/migration/fix_team_assignment_history.py

# Create employee records manually
python scripts/migration/manual_employee_creation.py

# Use migration utilities
python scripts/migration/migration_commands.py
```

## Migration Types

- **Data Migration** - Moving data between structures
- **Structure Updates** - Updating database schema or relationships
- **Data Fixes** - Correcting data inconsistencies
- **Manual Operations** - One-time data creation or updates

## Safety Guidelines

When running migration scripts:

1. **Always backup data first**
2. Test on development environment before production
3. Review what the script will do before running
4. Monitor for errors during execution
5. Validate results after completion

## Adding Migration Scripts

When adding migration scripts:

1. Include detailed documentation of what is migrated
2. Add validation checks before and after migration
3. Make scripts resumable if possible
4. Include rollback procedures where applicable
5. Log all changes for audit purposes
