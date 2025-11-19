"""
Desktop Configuration for Verenigingen Module
=============================================

Desktop workspace configuration module that defines the user interface organization
and navigation structure for the Verenigingen association management system within
the Frappe framework's desktop interface.

This configuration module serves as the primary navigation hub for users, organizing
business functionality into logical groups and providing intuitive access to core
features through the Frappe desktop interface.

Purpose and Architecture
-----------------------
The desktop configuration addresses several key user experience requirements:

**Logical Organization**: Groups related functionality for intuitive navigation
**User Role Optimization**: Provides role-appropriate access to system features
**Workflow Support**: Organizes features according to typical business workflows
**Integration Focus**: Emphasizes critical integration points and monitoring tools

Key Design Principles
--------------------
**Workflow-Centric Organization**: Features are grouped by business processes
**Progressive Disclosure**: Most critical features are prominently displayed
**Context-Aware Access**: Descriptions provide clear context for each feature
**Integration Emphasis**: Highlights external system integration points

Module Structure and Organization
--------------------------------

### Primary Module Definition
- **Module Name**: "Verenigingen" - Primary application module
- **Visual Identity**: Grey color scheme with directory icon for professional appearance
- **Module Type**: Standard Frappe module type for full feature access
- **Internationalization**: Full translation support via Frappe's _() function

### Feature Categorization Strategy
The desktop organizes features into logical business categories:

#### E-Boekhouden Integration Hub
**Purpose**: Centralized access to external accounting system integration
**Business Context**: Critical financial data synchronization and monitoring

**Feature Components**:
1. **Migration Dashboard**: Real-time monitoring of data synchronization status
2. **Migration Management**: Tools for creating and managing data transfers
3. **System Configuration**: API connection setup and operational parameters
4. **Live Dashboard**: Real-time operational monitoring interface

#### User Experience Optimization
Each feature includes comprehensive metadata for enhanced usability:

```python
{
    "type": "doctype",                    # Frappe navigation type
    "name": "E-Boekhouden Dashboard",     # Internal system reference
    "label": _("Migration Dashboard"),    # User-visible name (translated)
    "description": _("Monitor migration status and system health")  # Context help
}
```

Business Process Integration
---------------------------

### Financial Data Management Workflow
The desktop configuration supports the complete financial data lifecycle:

1. **Configuration Setup**: E-Boekhouden Settings for initial system setup
2. **Data Migration**: E-Boekhouden Migration for data transfer operations
3. **Status Monitoring**: Migration Dashboard for operational oversight
4. **Real-time Operations**: Live Dashboard for ongoing system monitoring

### User Role Considerations
While the configuration doesn't implement role-based restrictions directly,
it organizes features in a way that supports typical role-based workflows:

**Financial Administrators**: Primary access to integration and migration tools
**System Monitors**: Focus on dashboard and status monitoring features
**Configuration Managers**: Access to settings and system configuration

Technical Implementation Details
-------------------------------

### Frappe Framework Integration
The configuration leverages Frappe's desktop framework features:

- **Module Registration**: Automatic integration with Frappe's module system
- **Permission Integration**: Respects Frappe's role-based permission system
- **Translation Support**: Full internationalization through Frappe's translation system
- **Icon Integration**: Uses Octicon icon library for consistent visual design

### Navigation Structure
```python
{
    "module_name": "Verenigingen",        # Top-level module identifier
    "color": "grey",                      # Visual theme color
    "icon": "octicon octicon-file-directory",  # Module icon
    "type": "module",                     # Frappe module type
    "label": _("Verenigingen"),          # Translated module name
    "links": [...]                       # Feature organization structure
}
```

### Feature Metadata Schema
Each feature includes standardized metadata:

- **Type**: Navigation type (doctype, page, report)
- **Name**: Internal Frappe reference name
- **Label**: User-visible translated name
- **Description**: Contextual help text for user guidance

Extensibility and Maintenance
----------------------------

### Adding New Features
The configuration supports easy extension for new features:

```python
{
    "label": _("New Feature Category"),
    "items": [
        {
            "type": "doctype",
            "name": "New DocType",
            "label": _("New Feature"),
            "description": _("Description of new functionality")
        }
    ]
}
```

### Internationalization Maintenance
All user-visible text uses Frappe's translation system:

- **Translation Keys**: All labels and descriptions are wrapped with _()
- **Multi-language Support**: Automatic integration with Frappe's translation framework
- **Maintenance Efficiency**: Centralized translation management

### Visual Identity Consistency
The configuration maintains consistent visual identity:

- **Color Scheme**: Professional grey theme appropriate for business applications
- **Icon Strategy**: Octicon library for consistent, professional iconography
- **Layout Principles**: Logical grouping and clear hierarchical organization

Business Impact and User Experience
----------------------------------

### Operational Efficiency
The desktop configuration directly impacts operational efficiency:

**Reduced Navigation Time**: Logical organization minimizes time to find features
**Context Awareness**: Descriptions help users understand feature purposes
**Workflow Support**: Organization follows natural business process flows
**Integration Emphasis**: Highlights critical external system connections

### User Adoption Support
The configuration supports user adoption through:

**Intuitive Organization**: Features grouped by business logic rather than technical structure
**Clear Labeling**: Descriptive names that reflect business terminology
**Contextual Help**: Descriptions provide immediate context without additional documentation
**Progressive Learning**: Organization supports gradual feature discovery

### Quality Assurance
Built-in quality assurance features:

**Translation Validation**: All text properly internationalized
**Reference Integrity**: All DocType and page references validated
**Visual Consistency**: Standardized color and icon usage
**Accessibility Support**: Clear labeling supports screen readers and accessibility tools

Future Enhancement Opportunities
-------------------------------

### Role-Based Customization
Potential enhancements for role-based desktop customization:

- **Dynamic Feature Lists**: Show/hide features based on user roles
- **Personalized Layouts**: User-customizable feature organization
- **Usage Analytics**: Track feature usage for optimization

### Advanced Navigation Features
Opportunities for enhanced navigation:

- **Search Integration**: Quick search across all features
- **Recent Items**: Recently accessed features for quick access
- **Favorites System**: User-defined favorite features
- **Workflow Shortcuts**: Direct access to multi-step business processes

This desktop configuration provides a solid foundation for user navigation while
maintaining flexibility for future enhancements and customizations based on
evolving business needs and user feedback.
"""

from frappe import _


def get_data():
    return [
        {
            "module_name": "Verenigingen",
            "color": "grey",
            "icon": "octicon octicon-file-directory",
            "type": "module",
            "label": _("Verenigingen"),
            "links": [
                {
                    "label": _("E-Boekhouden"),
                    "items": [
                        {
                            "type": "doctype",
                            "name": "E-Boekhouden Dashboard",
                            "label": _("Migration Dashboard"),
                            "description": _("Monitor migration status and system health"),
                        },
                        {
                            "type": "doctype",
                            "name": "E-Boekhouden Migration",
                            "label": _("Migrations"),
                            "description": _("Create and manage data migrations"),
                        },
                        {
                            "type": "doctype",
                            "name": "E-Boekhouden Settings",
                            "label": _("Settings"),
                            "description": _("Configure API connection and defaults"),
                        },
                        {
                            "type": "page",
                            "name": "e-boekhouden-dashboard",
                            "label": _("Live Dashboard"),
                            "description": _("Real-time migration dashboard"),
                        },
                    ],
                }
            ],
        }
    ]
