"""
Chapter Managers Package
This package contains manager classes that handle specific aspects of chapter operations.
Each manager is responsible for a focused domain and provides a clean API for the Chapter class.
Managers:
- BaseManager: Base class with common manager functionality
- BoardManager: Handles all board member operations (add, remove, transitions, bulk ops)
Future Managers (planned):
- MemberManager: Handle chapter member operations
- CommunicationManager: Handle notifications and communications
- VolunteerIntegrationManager: Handle volunteer system integration
Usage:
    from .managers import BoardManager

    board_manager = BoardManager(chapter_doc)
    result = board_manager.add_board_member(volunteer_id, role, from_date)

    if not result['success']:
        frappe.throw(result.get('error', 'Operation failed'))
"""
from .base_manager import BaseManager
from .board_manager import BoardManager
from .communication_manager import CommunicationManager
from .member_manager import MemberManager
from .volunteer_integration_manager import VolunteerIntegrationManager

__all__ = [
    "BaseManager",
    "BoardManager",
    "MemberManager",
    "CommunicationManager",
    "VolunteerIntegrationManager",
]
# Version info
version = "1.0.0"
author = "Verenigingen Development Team"


# Convenience functions for common manager operations
def create_board_manager(chapter_doc):
    """
    Create a BoardManager instance

    Args:
        chapter_doc: Chapter document instance

    Returns:
        BoardManager: Board manager instance
    """
    return BoardManager(chapter_doc)


def get_board_summary(chapter_doc):
    """
    Get board summary for a chapter

    Args:
        chapter_doc: Chapter document instance

    Returns:
        dict: Board summary information
    """
    manager = BoardManager(chapter_doc)
    return manager.get_summary()


def bulk_board_operation(chapter_doc, operation_type, board_members_data):
    """
    Perform bulk board operations

    Args:
        chapter_doc: Chapter document instance
        operation_type: 'remove' or 'deactivate'
        board_members_data: List of board member data

    Returns:
        dict: Operation result
    """
    manager = BoardManager(chapter_doc)

    if operation_type == "remove":
        return manager.bulk_remove_board_members(board_members_data)
    elif operation_type == "deactivate":
        return manager.bulk_deactivate_board_members(board_members_data)
    else:
        return {"success": False, "error": f"Unknown operation type: {operation_type}"}


# Manager registry for dynamic manager creation
MANAGER_REGISTRY = {
    "board": BoardManager,
    "member": MemberManager,
    "communication": CommunicationManager,
    "volunteer_integration": VolunteerIntegrationManager,
}


def get_manager(manager_type, chapter_doc):
    """
    Get manager instance by type

    Args:
        manager_type: Type of manager ('board', 'member', etc.)
        chapter_doc: Chapter document instance

    Returns:
        BaseManager: Manager instance

    Raises:
        ValueError: If manager type not found
    """
    manager_class = MANAGER_REGISTRY.get(manager_type)
    if not manager_class:
        raise ValueError(f"Unknown manager type: {manager_type}")

    return manager_class(chapter_doc)


def get_available_managers():
    """
    Get list of available manager types

    Returns:
        list: Available manager type names
    """
    return list(MANAGER_REGISTRY.keys())
