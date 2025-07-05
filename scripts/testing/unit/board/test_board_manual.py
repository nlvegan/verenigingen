#!/usr/bin/env python3
"""
Manual test for board member addition without console
"""
import subprocess
import sys


def test_board_addition():
    """Test adding Parko to board"""

    # First, let's check the current state
    cmd1 = [
        "bench",
        "--site",
        "dev.veganisme.net",
        "execute",
        "frappe.db.sql",
        "--args",
        "SELECT name, volunteer_name, chapter_role FROM `tabChapter Board Member` WHERE parent='Antwerpen' AND is_active=1",
    ]

    cmd2 = [
        "bench",
        "--site",
        "dev.veganisme.net",
        "execute",
        "frappe.db.sql",
        "--args",
        "SELECT member, member_name, enabled FROM `tabChapter Member` WHERE parent='Antwerpen' AND enabled=1",
    ]

    print("=== Current Board Members ===")
    try:
        result1 = subprocess.run(cmd1, capture_output=True, text=True, cwd="/home/frappe/frappe-bench")
        print("STDOUT:", result1.stdout)
        print("STDERR:", result1.stderr)
    except Exception as e:
        print(f"Error running cmd1: {e}")

    print("\n=== Current Chapter Members ===")
    try:
        result2 = subprocess.run(cmd2, capture_output=True, text=True, cwd="/home/frappe/frappe-bench")
        print("STDOUT:", result2.stdout)
        print("STDERR:", result2.stderr)
    except Exception as e:
        print(f"Error running cmd2: {e}")


if __name__ == "__main__":
    test_board_addition()
