# Member Portal Home Page Setup

This document explains the implementation of automatic member portal redirects for users with Member roles.

## 🎯 **What Was Implemented**

The system now automatically redirects members to `/member_portal` when they log in, making it their default landing page instead of the generic home page or backend.

## 🔧 **Components Added**

### 1. **Authentication Hooks** (`auth_hooks.py`)
- **Server-side login redirect**: When members log in, they are automatically redirected to `/member_portal`
- **Role-based detection**: Identifies users with Member role or linked member records
- **Volunteer support**: Also handles volunteers appropriately
- **Session management**: Handles login/logout events

### 2. **Client-side JavaScript** (`member_portal_redirect.js`)
- **Additional redirect logic**: Handles cases where server-side redirect doesn't apply
- **Navigation helper**: Redirects from generic pages to member portal for members
- **Automatic loading**: Included in all web pages via hooks

### 3. **Utility Functions** (`member_portal_utils.py`)
- **Bulk setup**: Set home page for all existing members at once
- **Individual setup**: Set home page for specific users
- **Statistics**: Get adoption rates and portal usage stats
- **Maintenance**: Background sync for new members

### 4. **Management Interface** (Verenigingen Settings)
- **Portal Statistics**: View how many members use the portal as home page
- **Bulk Setup**: One-click setup for all existing members
- **Testing**: Test redirect logic for current user

### 5. **Setup Script** (`setup_member_portal_home.py`)
- **Initial setup**: Command-line tool to configure existing members
- **Statistics reporting**: Shows before/after adoption rates

## 🚀 **How It Works**

### **For New Members**
1. When a member logs in, the `on_session_creation` hook is triggered
2. The system checks if the user has Member role or linked member record
3. If yes, sets `frappe.local.response["home_page"] = "/member_portal"`
4. Member is automatically redirected to the portal

### **For Existing Members**
1. Use the management interface or setup script to configure existing users
2. Updates the User doctype's `home_page` field to `/member_portal`
3. Next login will redirect to member portal

### **Smart Detection**
The system identifies members through:
- **Direct link**: User record linked to Member doctype
- **Role-based**: User has "Member" role assigned
- **Volunteer detection**: Users with volunteer roles can also be redirected

## 📋 **Setup Instructions**

### **1. Automatic Setup (Recommended)**
1. Go to **Verenigingen Settings**
2. Look for the **Member Portal** button group
3. Click **"Setup Portal Home Pages"**
4. Confirm to set `/member_portal` as home page for all members

### **2. Manual Setup via Script**
```bash
cd /home/frappe/frappe-bench/apps/verenigingen
python3 setup_member_portal_home.py
```

### **3. View Statistics**
- In **Verenigingen Settings**, click **"View Portal Stats"**
- Shows total members, adoption rate, and setup status

### **4. Test the Setup**
- In **Verenigingen Settings**, click **"Test Portal Redirect"**
- Shows what home page the current user should get
- Option to navigate there immediately

## 🔍 **Monitoring and Maintenance**

### **Check Current Status**
```python
# In Frappe console
from verenigingen.utils.member_portal_utils import get_member_portal_stats
stats = get_member_portal_stats()
print(stats)
```

### **Update Individual Member**
```python
# In Frappe console
from verenigingen.utils.member_portal_utils import set_member_home_page
result = set_member_home_page("member@example.com", "/member_portal")
print(result)
```

### **Sync New Members**
```python
# In Frappe console or scheduled job
from verenigingen.utils.member_portal_utils import sync_member_user_home_pages
updated_count = sync_member_user_home_pages()
print(f"Updated {updated_count} members")
```

## 🎛️ **Configuration Options**

### **Customize Redirect Logic**
Edit `auth_hooks.py` to modify:
- Which roles get redirected
- Redirect destinations
- Additional validation logic

### **Different Portal for Volunteers**
In `auth_hooks.py`, change volunteer redirect:
```python
if has_volunteer_role(user):
    frappe.local.response["home_page"] = "/volunteer_portal"  # Custom volunteer portal
```

### **Conditional Redirects**
Add custom logic in `auth_hooks.py`:
```python
# Example: Different portals based on member type
member_doc = frappe.get_doc("Member", member_record)
if member_doc.membership_type == "Premium":
    frappe.local.response["home_page"] = "/premium_portal"
```

## 🛡️ **Security Considerations**

### **Access Control**
- Only users with Member role are redirected
- System users retain access to `/app`
- Administrators can override settings

### **Fallback Behavior**
- If member portal is unavailable, users get default homepage
- Error handling prevents login failures
- Graceful degradation for edge cases

### **Permission Validation**
- Member portal access is still controlled by page-level permissions
- Redirect doesn't grant additional access
- Users must still have proper roles for portal features

## 📊 **Expected Behavior**

### **Member Users**
- ✅ Login → Automatic redirect to `/member_portal`
- ✅ Visiting `/` or `/home` → Redirect to `/member_portal`
- ✅ Direct navigation to `/member_portal` → Works normally

### **System Users**
- ✅ Login → Normal redirect to `/app`
- ✅ Full backend access maintained
- ✅ Can override member portal settings

### **Volunteers**
- ✅ Can be redirected to member portal (configurable)
- ✅ Future: Can have separate volunteer portal
- ✅ Maintains access to relevant features

## 🔧 **Troubleshooting**

### **Members Not Redirecting**
1. Check if user has Member role: `frappe.get_roles("user@example.com")`
2. Check if member record is linked: `frappe.db.get_value("Member", {"user": "user@example.com"}, "name")`
3. Verify home page setting: `frappe.db.get_value("User", "user@example.com", "home_page")`

### **Redirect Not Working**
1. Check browser cache (hard refresh)
2. Verify authentication hooks are enabled in `hooks.py`
3. Check for JavaScript errors in browser console

### **Wrong Portal for User Type**
1. Review role assignments
2. Check logic in `auth_hooks.py`
3. Use "Test Portal Redirect" in Verenigingen Settings

## 📈 **Benefits**

1. **Better User Experience**: Members land directly on relevant content
2. **Reduced Confusion**: No need to navigate from generic homepage
3. **Role-based Navigation**: Automatic routing based on user type
4. **Easy Management**: Bulk setup and monitoring tools
5. **Future-proof**: Extensible for different user types and portals

## 🔄 **Future Enhancements**

1. **Volunteer Portal**: Separate portal for volunteers
2. **Conditional Redirects**: Based on member status, type, chapter
3. **Personalization**: User-configurable home page preferences
4. **Mobile Optimization**: Mobile-specific portal routing
5. **Analytics**: Track portal usage and engagement

---

The member portal home page setup is now complete and ready to use! Members will automatically be directed to their portal upon login, providing a streamlined and user-friendly experience.
