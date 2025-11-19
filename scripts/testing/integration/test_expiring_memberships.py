#!/usr/bin/env python3

import frappe


def test_expiring_memberships_report():
    """Test the expiring memberships report"""

    print("Testing Expiring Memberships Report...")

    try:
        # Test SQL query directly first
        result = frappe.db.sql(
            """
            select ms.membership_type, ms.name, m.name, m.member_name, m.email, ms.expiry_date
            from `tabMember` m
            inner join (
                select
                    memb.name,
                    memb.membership_type,
                    memb.member,
                    COALESCE(
                        (SELECT next_invoice_date 
                         FROM `tabMembership Dues Schedule` 
                         WHERE member = memb.member 
                         ORDER BY creation DESC 
                         LIMIT 1),
                        memb.renewal_date
                    ) as expiry_date
                from `tabMembership` memb
                where memb.status in ('Active', 'Pending')
                  and (
                      (SELECT next_invoice_date 
                       FROM `tabMembership Dues Schedule` 
                       WHERE member = memb.member 
                       ORDER BY creation DESC 
                       LIMIT 1) is not null
                      or memb.renewal_date is not null
                  )
            ) ms on m.name = ms.member
            where month(ms.expiry_date) = 12 and year(ms.expiry_date) = 2025
            order by ms.expiry_date asc
            LIMIT 5
            """,
            as_dict=1,
        )

        print(f"✅ SQL query works! Found {len(result)} records")
        for record in result:
            print(f"  - {record.member_name}: {record.expiry_date}")

        # Test the report function
        from verenigingen.verenigingen.report.expiring_memberships.expiring_memberships import execute

        filters = {"month": "Dec", "fiscal_year": "2025"}

        columns, data = execute(filters)
        print(f"✅ Report function works! {len(columns)} columns, {len(data)} rows")
        print("Columns:", [col.split(":")[0] for col in columns])

        return {"success": True, "records": len(data)}

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    result = test_expiring_memberships_report()
    print(f"\nResult: {result}")

    frappe.destroy()
