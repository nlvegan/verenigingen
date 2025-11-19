# Database Table Size Analysis Report

## Overview

Visual analysis of database table storage with detailed metrics and optimization tools.

## Features

### Visual Display
- **Stacked bar chart** showing top 15 tables by size (Data + Index)
- **Color-coded table rows** based on size and percentage thresholds
- **Visual percentage bars** in the table name column

### Metrics Displayed
- **Row Count** - Number of records in each table
- **Data Size** - Size of actual data in MB
- **Index Size** - Size of indexes in MB
- **Total Size** - Combined data + index size
- **Average Row Size** - Average bytes per record
- **Percentage of Total** - What % of database this table represents
- **Engine** - Database engine (InnoDB, MyISAM, etc.)
- **Table Type** - DocType, Child Table, System, or Other

### Filters
- **Table Type** - Filter by DocType, Child Table, System, or Other
- **Minimum Size (MB)** - Only show tables above a certain size
- **DocType Filter** - Search for specific DocTypes by name

### Actions
- **Optimize Tables** - Run MySQL OPTIMIZE TABLE to reclaim space
- **Analyze Tables** - Update MySQL table statistics for better query planning
- **Export to CSV** - Export the full report data

## Color Coding

### Percentage Column
- **Red (>10%)** - Table consuming >10% of database
- **Orange (5-10%)** - Table consuming 5-10% of database
- **Blue (1-5%)** - Table consuming 1-5% of database
- **Default (<1%)** - Small tables

### Total Size Column
- **Red (>100MB)** - Very large tables
- **Orange (50-100MB)** - Large tables
- **Blue (10-50MB)** - Medium tables
- **Default (<10MB)** - Small tables

## Security

- **System Manager role required** to access the report
- **System Manager role required** for Optimize/Analyze operations
- All actions are logged for audit purposes

## Usage Tips

1. **Identify storage hogs** - Look for tables with high percentage values
2. **Find optimization candidates** - Large tables with low row counts may need index review
3. **Monitor growth** - Run periodically to track database growth trends
4. **Optimize regularly** - Use the Optimize button to reclaim space from deleted records
5. **Update statistics** - Use Analyze button after bulk data changes for better query performance

## Technical Details

- Queries `information_schema.TABLES` for accurate size information
- Data is cached per report run (refresh to update)
- Total row calculation includes sum of all filtered tables
- Chart shows top 15 tables regardless of filters (for readability)
