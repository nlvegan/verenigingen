#!/usr/bin/env python3
"""
Debug board member addition - console version
"""
import frappe

# Get the chapter
chapter = frappe.get_doc("Chapter", "Antwerpen")
print(f"Chapter: {chapter.name}")

# Check current board members
print("\nCurrent board members:")
for board_member in chapter.board_members:
    print(f"- {board_member.person_id} ({board_member.role})")

# Check current chapter members
print("\nCurrent chapter members:")
for member in chapter.chapter_members:
    print(f"- {member.person_id}")

# Check if Parko exists as a person
try:
    parko = frappe.get_doc("Person", "parko")
    print(f"\nParko found: {parko.name}")
except frappe.DoesNotExistError:
    print("\nParko person not found!")

# Find Parko in board members
parko_in_board = False
for board_member in chapter.board_members:
    if board_member.person_id == "parko":
        parko_in_board = True
        print("Parko is already in board")
        break

if not parko_in_board:
    print("Parko is NOT in board")

# Find Parko in chapter members
parko_in_chapter = False
for member in chapter.chapter_members:
    if member.person_id == "parko":
        parko_in_chapter = True
        print("Parko is in chapter members")
        break

if not parko_in_chapter:
    print("Parko is NOT in chapter members - automatic addition failed!")

# Test the BoardManager method directly
print("\n=== Testing BoardManager directly ===")
from verenigingen.verenigingen.doctype.chapter.managers.board_manager import BoardManager

board_manager = BoardManager(chapter)

# Test adding Parko to board
print("Adding Parko to board via BoardManager...")
board_manager.add_board_member("parko", "Member")

print("Board members after addition:")
for board_member in chapter.board_members:
    print(f"- {board_member.person_id} ({board_member.role})")

print("Chapter members after addition:")
for member in chapter.chapter_members:
    print(f"- {member.person_id}")

# Save the chapter
print("Saving chapter...")
chapter.save()

print("=== Final state after save ===")
chapter.reload()

print("Final board members:")
for board_member in chapter.board_members:
    print(f"- {board_member.person_id} ({board_member.role})")

print("Final chapter members:")
for member in chapter.chapter_members:
    print(f"- {member.person_id}")
