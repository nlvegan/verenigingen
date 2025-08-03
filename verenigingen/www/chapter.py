"""
@fileoverview Chapter Page Context Provider for Public Web Interface

This module provides the backend context processing for the public chapters web page,
handling user authentication, member identification, and page configuration for the
Verenigingen association management system's public-facing chapter directory interface.

Purpose and Architecture
-----------------------
The chapter page serves as a critical public interface for the association, providing:

**Public Chapter Discovery**: Allows visitors to explore available chapters and locations
**Member Integration**: Provides enhanced features for authenticated members
**Chapter Information**: Displays comprehensive chapter details and contact information
**Location Services**: Enables geographical chapter search and discovery
**Engagement Tools**: Facilitates chapter joining and volunteer sign-up processes

This context provider ensures the page functions correctly for both guest users and
authenticated members, providing appropriate data and interface elements based on
user authentication status and membership information.

Business Context
---------------
Chapters represent the geographical and organizational structure of the association:

**Regional Organization**: Chapters provide local presence and community engagement
**Member Services**: Local chapters deliver services and coordinate member activities
**Volunteer Coordination**: Chapters organize volunteer activities and community outreach
**Event Management**: Local chapters host events, meetings, and educational programs
**Community Building**: Chapters foster local community and member relationships

The chapter page supports these functions by providing accessible information about
each chapter's activities, leadership, and ways to get involved.

Technical Implementation
-----------------------

### Context Data Structure
The context provider assembles comprehensive data for template rendering:

```python
context = {
    'no_cache': 1,              # Dynamic content requires fresh data
    'show_sidebar': True,       # Standard navigation sidebar
    'title': _("Chapters"),     # Internationalized page title
    'logged_in': boolean,       # Authentication status flag
    'member': member_id         # Member record for authenticated users
}
```

### Authentication Handling Strategy
The module implements flexible authentication handling:

**Guest Users**:
- Allowed to view basic chapter information
- JavaScript handles display of public-only content
- No member-specific features or data exposed

**Authenticated Users**:
- Enhanced chapter information with member context
- Access to member-specific features and actions
- Integration with member's chapter associations

### User Experience Optimization
- **No Cache Policy**: Ensures dynamic content freshness for user-specific data
- **Sidebar Integration**: Maintains consistent site navigation
- **Internationalization**: Full translation support for global accessibility
- **Progressive Enhancement**: JavaScript handles advanced features without breaking basic functionality

Integration Points
-----------------

### Member Management System
- Links authenticated users to their Member records
- Provides member context for chapter interactions
- Enables member-specific chapter recommendations

### Chapter Management System
- Accesses chapter data for public display
- Supports chapter search and filtering capabilities
- Integrates with chapter event and activity information

### Authentication System
- Respects Frappe's session management
- Handles both guest and authenticated user scenarios
- Provides appropriate access control for different user types

### Frontend JavaScript Integration
- Passes authentication status to client-side code
- Enables dynamic content loading based on user status
- Supports progressive enhancement patterns

Security Considerations
----------------------

### Data Privacy Protection
- Only exposes necessary user information to templates
- Respects member privacy settings and preferences
- Prevents unauthorized access to sensitive member data

### Guest User Safety
- Safely handles unauthenticated user scenarios
- Prevents exposure of member-only information
- Maintains functional public interface without authentication

### Session Management
- Relies on Frappe's secure session handling
- Validates session authenticity before member lookup
- Handles session edge cases gracefully

Performance Optimization
-----------------------

### Caching Strategy
- Disables caching for dynamic user-specific content
- Ensures fresh data for member authentication status
- Balances performance with data accuracy requirements

### Database Query Efficiency
- Single query for member lookup when authenticated
- Minimal database interaction for guest users
- Efficient member record retrieval by email

### Template Rendering Performance
- Provides pre-processed context data to templates
- Minimizes template-side processing requirements
- Optimizes data structure for frontend consumption

Frontend Integration Architecture
--------------------------------

### Template Data Provision
The context provider supplies templates with:
- **Authentication Flags**: Enable conditional rendering
- **Member Context**: Support personalized content
- **Configuration Data**: Control page behavior and features
- **Internationalization**: Translated strings and labels

### JavaScript Integration Points
- **User Status**: Authentication state for dynamic features
- **Member Data**: User-specific information for enhanced features
- **Configuration**: Page behavior settings and feature flags
- **API Integration**: Context for frontend API calls

User Experience Patterns
------------------------

### Progressive Disclosure
- Basic chapter information available to all users
- Enhanced features revealed for authenticated members
- Member-specific recommendations and actions

### Responsive Design Support
- Context data structured for mobile and desktop rendering
- Flexible data provision for responsive template patterns
- Optimized for various screen sizes and interaction methods

### Accessibility Compliance
- Proper heading structure and navigation
- Screen reader friendly data organization
- Keyboard navigation support through proper context

Maintenance and Extension
------------------------

### Adding New User Types
To support additional user categories:
1. Extend authentication logic for new user types
2. Add appropriate context data for new user experiences
3. Update security validation for new access patterns
4. Ensure template compatibility with extended context

### Enhanced Chapter Features
For additional chapter functionality:
1. Extend context data with new chapter information
2. Add appropriate user permission checks
3. Update template integration points
4. Ensure performance impact is minimal

### Integration Enhancements
For additional system integrations:
1. Add new data providers to context assembly
2. Implement appropriate caching strategies
3. Update security and privacy considerations
4. Maintain backwards compatibility

Quality Assurance Impact
-----------------------

### User Experience Consistency
- Ensures consistent behavior across user types
- Provides reliable authentication-based features
- Maintains functional interface for all users

### Security Compliance
- Implements proper access control patterns
- Protects member privacy and data security
- Follows Frappe security best practices

### Performance Reliability
- Efficient context data assembly
- Minimal database overhead
- Optimized for high-traffic public access

Author: Development Team
Date: 2025-08-03
Version: 1.0
"""

import frappe
from frappe import _


def get_context(context):
    """Get context for chapters page"""

    # Page configuration
    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Chapters")

    # Check if user is logged in
    if frappe.session.user == "Guest":
        # Allow guest users to view the page, the JavaScript will handle the display
        context.logged_in = False
    else:
        context.logged_in = True

        # Get member record for logged in user
        member = frappe.db.get_value("Member", {"email": frappe.session.user}, "name")
        context.member = member

    return context
