# User-Member Profile Picture Synchronization

## Overview

Bidirectional synchronization system that keeps profile pictures in sync between User and Member records.

## Implementation Date
2025-11-10

## Features

### Automatic Bidirectional Sync
- When a Member's `image` field is updated, the linked User's `user_image` field is automatically synchronized
- When a User's `user_image` field is updated, the linked Member's `image` field is automatically synchronized

### Safeguards
- **Infinite Loop Prevention**: Uses `frappe.flags.syncing_user_member_image` flag to prevent circular updates
- **Change Detection**: Only syncs when the image field actually changes (not on every save)
- **Error Handling**: Gracefully handles edge cases (missing records, null values) without blocking saves
- **Audit Trail**: Logs all sync operations for troubleshooting

## Architecture

### Hook Configuration
Located in `hooks.py`:

**Member DocType**:
```python
"Member": {
    "on_update": [
        "verenigingen.utils.user_member_image_sync.sync_member_image_to_user",
    ],
}
```

**User DocType**:
```python
"User": {
    "on_update": [
        "verenigingen.utils.user_member_image_sync.sync_user_image_to_member",
    ],
}
```

### Sync Module
File: `verenigingen/utils/user_member_image_sync.py`

Contains two main functions:
1. `sync_member_image_to_user(doc, method=None)` - Syncs Member.image → User.user_image
2. `sync_user_image_to_member(doc, method=None)` - Syncs User.user_image → Member.image

## Usage

The synchronization happens automatically. No manual intervention required.

### Example Workflow

1. **Member Portal**: User updates their profile picture in the Member portal
   - Member.image is updated
   - Hook triggers `sync_member_image_to_user`
   - User.user_image is automatically synchronized

2. **User Profile**: User updates their profile picture in User settings
   - User.user_image is updated
   - Hook triggers `sync_user_image_to_member`
   - Member.image is automatically synchronized

## Edge Cases Handled

1. **Member without User**: Sync gracefully skips if no user is linked
2. **User without Member**: Sync gracefully skips if no member record exists
3. **No Change**: Sync only triggers when image actually changes
4. **Null Values**: Handles null/empty image values correctly
5. **Permission Issues**: Uses `ignore_permissions=True` to avoid permission errors during sync

## Testing

Comprehensive test suite in `verenigingen/tests/test_user_member_image_sync.py`

Run tests with:
```bash
bench --site dev.veganisme.net run-tests --module verenigingen.tests.test_user_member_image_sync
```

Test coverage includes:
- ✅ Member image syncs to User
- ✅ User image syncs to Member
- ✅ Infinite loop prevention
- ✅ Missing user handling
- ✅ Missing member handling
- ✅ Change detection (only sync on actual changes)

## Performance Considerations

- **Minimal Overhead**: Only executes on actual image field changes
- **Single Database Operation**: Each sync is one `save()` operation
- **No Queue Jobs**: Synchronous operation ensures immediate consistency
- **Flag-based Prevention**: Prevents cascading updates efficiently

## Security

- Operations use `ignore_permissions=True` to ensure sync works regardless of user permissions
- Sync is internal-only, triggered by document save events
- Comprehensive logging for audit trail
- No direct user input in sync operations

## Troubleshooting

### Check Sync Logs
```python
# In Frappe Console
frappe.get_all("Error Log",
    filters={"error": ["like", "%Image Sync%"]},
    order_by="modified desc",
    limit=10
)
```

### Manual Sync
If sync fails, you can manually sync:
```python
# Sync Member image to User
from verenigingen.utils.user_member_image_sync import sync_member_image_to_user
member = frappe.get_doc("Member", "MEMBER-001")
sync_member_image_to_user(member)

# Sync User image to Member
from verenigingen.utils.user_member_image_sync import sync_user_image_to_member
user = frappe.get_doc("User", "user@example.com")
sync_user_image_to_member(user)
```

### Verify Link
```python
# Check if Member has linked User
member = frappe.get_doc("Member", "MEMBER-001")
print(f"Linked User: {member.user}")

# Check if User has linked Member
member_name = frappe.db.get_value("Member", {"user": "user@example.com"}, "name")
print(f"Linked Member: {member_name}")
```

## Future Enhancements

Potential improvements for future consideration:
- Webhook notifications for external systems
- Image transformation/resizing during sync
- Configurable sync enable/disable per member
- Sync history tracking in dedicated table

## Related Documentation

- Member DocType: `verenigingen/doctype/member/`
- User DocType: Frappe Framework core
- Hook System: `verenigingen/hooks.py`
- Test Suite: `verenigingen/tests/test_user_member_image_sync.py`
