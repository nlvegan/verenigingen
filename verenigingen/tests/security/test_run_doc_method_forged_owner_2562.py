"""#2562: ``run_doc_method(docs=...)`` must not let a caller satisfy an ``if_owner`` row by
posting ``owner=<themselves>``.

``frappe.handler.run_doc_method`` with ``docs`` builds the document from the CLIENT's dict and
checks permission on it, so the owner Frappe compared with the session user was whatever the client
posted. The four doctypes with an ``if_owner`` row (Donation Campaign, Member, Membership,
Contribution Amendment Request) are probed here through a real WSGI POST (v1 ``/api/method`` and v2
``/api/v2/method``) as an API-key user who holds only the if_owner roles, in a subprocess with its
own DB connection and committed fixtures (removed again in its ``finally``).

Measured on develop (c843d212e), same probe: Donation Campaign methods 200 on v1 (v2 refuses:
POST needs write); ``Member.get_current_membership_fee`` 200 on v1 AND v2; an unknown name 404 while
an honest foreign owner 403. ``Member`` is a separate path: its ``has_permission()`` controller
method calls ``has_member_permission`` directly, so Frappe's hook list never runs for it.

PROBE SHORTCUTS: Membership and Contribution Amendment Request rows are inserted with ignore flags;
their ``get_billing_amount`` / ``get_impact_preview`` are ``high_security_api`` and refused this
caller at the decorator on develop too, so for those two the guard is asserted at the permission
layer (``frappe.has_permission`` on a forged doc), not through a method that ran. Query count is not
compared over WSGI.
"""

import json
import os
import subprocess
import sys

import frappe
from frappe.utils import get_bench_path

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

_PROBE = r"""
import json, sys, uuid, frappe
from frappe.utils import add_days, today
from werkzeug.test import Client
SITE=sys.argv[1]
frappe.init(site=SITE); frappe.connect(); frappe.clear_cache()
import verenigingen; sys.stderr.write("PKG %s\n"%verenigingen.__file__)
frappe.set_user("Administrator")
tag=uuid.uuid4().hex[:6]
made=[]
def mk(doc, **flags):
    d=frappe.get_doc(doc); d.flags.ignore_permissions=True
    for k in flags: setattr(d.flags,k,True)
    d.insert(); made.append((d.doctype,d.name)); return d
def user(email, roles):
    u=frappe.get_doc({"doctype":"User","email":email,"first_name":"P","send_welcome_email":0,"roles":[{"role":r} for r in roles]}).insert()
    made.append(("User",email)); u.api_key=frappe.generate_hash(length=15); sec=frappe.generate_hash(length=15); u.api_secret=sec; u.save()
    return {"email":email,"hdr":{"Authorization":f"token {u.api_key}:{sec}","X-Frappe-Site-Name":SITE}}
out={}
try:
    attacker=user(f"forge-a-{tag}@test.invalid",["Verenigingen Volunteer","Verenigingen Member"])
    staff=user(f"forge-s-{tag}@test.invalid",["System Manager","Accounts User","Verenigingen Administrator"])
    camp=mk({"doctype":"Donation Campaign","campaign_name":"Forge "+tag,"campaign_type":"Other","status":"Active","start_date":"2026-01-01"})
    member=mk({"doctype":"Member","first_name":"Forge","last_name":tag,"email":f"fm-{tag}@test.invalid"}, ignore_customer_sync=True)
    mt=frappe.db.get_value("Membership Type",{}) or mk({"doctype":"Membership Type","membership_type_name":"Forge "+tag,"amount":10,"billing_period":"Annual"},ignore_mandatory=True,ignore_links=True).name
    cases={"Donation Campaign":(camp.name,["get_project_summary","get_recent_donations","get_top_donors"]),
           "Member":(member.name,["get_current_membership_fee","get_address_members_html"])}
    try:
        ms=mk({"doctype":"Membership","member":member.name,"membership_type":mt,"start_date":"2026-01-01","status":"Active"},ignore_mandatory=True,ignore_links=True,ignore_validate=True)
        cases["Membership"]=(ms.name,["get_billing_amount"])
        car=mk({"doctype":"Contribution Amendment Request","membership":ms.name,"amendment_type":"Fee Change","status":"Draft","requested_date":today(),"effective_date":add_days(today(),30)},ignore_mandatory=True,ignore_links=True,ignore_validate=True)
        cases["Contribution Amendment Request"]=(car.name,["get_impact_preview"])
    except Exception as e:
        out["setup_error"]=repr(e)[:300]
    for dt,(name,_m) in cases.items():
        forged=frappe.get_doc({"doctype":dt,"name":name,"owner":attacker["email"]})
        honest=frappe.get_doc({"doctype":dt,"name":name,"owner":"Administrator"})
        unknown=frappe.get_doc({"doctype":dt,"name":name+"-nope","owner":attacker["email"]})
        out["perm."+dt]={"forged":bool(frappe.has_permission(dt,"read",doc=forged,user=attacker["email"])),
            "unknown":bool(frappe.has_permission(dt,"read",doc=unknown,user=attacker["email"]))}
    frappe.db.commit(); frappe.destroy()
    import frappe.app
    c=Client(frappe.app.application,use_cookies=False)
    def call(who, dt, name, m, owner, v2=False, detail=False, extra=None):
        frappe.init(site=SITE); frappe.connect()
        mod=frappe.db.get_value(dt,name,"modified") if frappe.db.exists(dt,name) else None
        frappe.destroy()
        doc={"doctype":dt,"name":name,"owner":owner,"modified":str(mod) if mod else "2026-01-01 00:00:00"}
        for k,v in (extra or {}).items():
            if v is None: doc.pop(k,None)
            else: doc[k]=v
        if v2:
            r=c.post("/api/v2/method/run_doc_method",json={"method":m,"document":doc},headers=who["hdr"])
        else:
            r=c.post("/api/method/run_doc_method",data={"method":m,"docs":json.dumps(doc)},headers=who["hdr"])
        return r.status_code if not detail else (r, name)
    def channels(dt, name, m):
        frappe.init(site=SITE); frappe.connect(); before=frappe.db.count("Error Log"); frappe.destroy()
        r,_n=call(attacker,dt,name,m,attacker["email"],detail=True)
        frappe.init(site=SITE); frappe.connect(); delta=frappe.db.count("Error Log")-before; frappe.destroy()
        body=r.get_data(as_text=True).replace(name,"<NAME>")
        j=json.loads(body)
        return {"status":r.status_code,"exc_type":j.get("exc_type"),"messages":j.get("_server_messages"),"error_logs":delta}
    if "Donation Campaign" in cases:
        n=cases["Donation Campaign"][0]
        out["oracle.forged"]=channels("Donation Campaign",n,"get_project_summary")
        out["oracle.unknown"]=channels("Donation Campaign",n+"-nope","get_project_summary")
    for dt,(name,methods) in cases.items():
        for m in methods:
            out[f"{dt}.{m}"]={"forged_v1":call(attacker,dt,name,m,attacker["email"]),
                "forged_v2":call(attacker,dt,name,m,attacker["email"],v2=True),
                "islocal_1_v1":call(attacker,dt,name,m,attacker["email"],extra={"__islocal":1}),
                "islocal_str_v1":call(attacker,dt,name,m,attacker["email"],extra={"__islocal":"1"}),
                "islocal_1_v2":call(attacker,dt,name,m,attacker["email"],v2=True,extra={"__islocal":1}),
                "noname_v1":call(attacker,dt,name,m,attacker["email"],extra={"name":None}),
                "noname_islocal_v1":call(attacker,dt,name,m,attacker["email"],extra={"name":None,"__islocal":1}),
                "honest_foreign_v1":call(attacker,dt,name,m,"Administrator"),
                "unknown_forged_v1":call(attacker,dt,name+"-nope",m,attacker["email"]),
                "staff_v1":call(staff,dt,name,m,"Administrator")}
finally:
    frappe.init(site=SITE); frappe.connect(); frappe.set_user("Administrator")
    for dt,n in reversed(made):
        try: frappe.delete_doc(dt,n,force=1,ignore_permissions=True)
        except Exception as e: sys.stderr.write("cleanup %s %s %r\n"%(dt,n,e))
    frappe.db.commit(); frappe.clear_cache()
print("RESULT"+json.dumps(out,indent=1))

"""


class TestRunDocMethodForgedOwner2562(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        result = subprocess.run(
            [sys.executable, "-c", _PROBE, frappe.local.site],
            cwd=os.path.join(get_bench_path(), "sites"),
            capture_output=True,
            text=True,
            timeout=400,
            env={**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)},
        )
        line = next((x for x in result.stdout.splitlines() if x.startswith("RESULT")), None)
        if result.returncode != 0 or line is None:
            raise AssertionError(result.stdout + "\n" + result.stderr)
        cls.out = json.loads(result.stdout[result.stdout.index("RESULT") + len("RESULT") :])

    def test_probe_set_up_every_doctype(self):
        self.assertNotIn("setup_error", self.out, self.out.get("setup_error"))

    def test_forged_owner_is_refused_on_every_whitelisted_campaign_method(self):
        for method in ("get_project_summary", "get_recent_donations", "get_top_donors"):
            row = self.out[f"Donation Campaign.{method}"]
            with self.subTest(method=method):
                self.assertEqual((row["forged_v1"], row["forged_v2"]), (403, 403))

    def test_a_client_supplied_islocal_or_missing_name_does_not_skip_the_guard(self):
        """The posted dict controls __islocal, so the guard must not honour it (review of 1c27dd655)."""
        for key in ("Donation Campaign.get_recent_donations", "Member.get_current_membership_fee"):
            row = self.out[key]
            for variant in ("islocal_1_v1", "islocal_str_v1", "islocal_1_v2", "noname_v1", "noname_islocal_v1"):
                with self.subTest(method=key, variant=variant):
                    self.assertEqual(row[variant], 403)

    def test_forged_owner_is_refused_on_a_foreign_member_method_on_both_routes(self):
        row = self.out["Member.get_current_membership_fee"]
        self.assertEqual((row["forged_v1"], row["forged_v2"]), (403, 403))

    def test_an_unknown_name_is_refused_like_a_forbidden_one_on_every_compared_channel(self):
        self.assertEqual(self.out["oracle.forged"], self.out["oracle.unknown"])
        self.assertEqual(self.out["oracle.forged"]["status"], 403)
        for row in self.out.values():
            if isinstance(row, dict) and "unknown_forged_v1" in row:
                self.assertEqual(row["unknown_forged_v1"], row["honest_foreign_v1"])

    def test_staff_can_still_run_the_methods(self):
        """Control: a real row exists and a blanket-access caller still gets a 200."""
        for key in ("Donation Campaign.get_recent_donations", "Member.get_current_membership_fee"):
            self.assertEqual(self.out[key]["staff_v1"], 200, key)

    def test_the_permission_layer_refuses_a_forged_owner_on_all_four_doctypes(self):
        """Membership was already refused on develop (its hook demands the caller's own member link),
        so for it this is a control, not a red; the other three are red without the guard."""
        self._perm_layer()

    def _perm_layer(self):
        for doctype in ("Donation Campaign", "Member", "Membership", "Contribution Amendment Request"):
            with self.subTest(doctype=doctype):
                self.assertEqual(self.out["perm." + doctype], {"forged": False, "unknown": False})

    def test_the_real_owner_keeps_if_owner_access(self):
        """Control: a user whose OWN row it is still passes (a refuse-everything guard cannot)."""
        email = f"own-{frappe.generate_hash()[:8]}@test.invalid"
        user = self.create_test_user(email, roles=["Verenigingen Volunteer"]).name
        campaign = frappe.get_doc(
            {
                "doctype": "Donation Campaign",
                "campaign_name": f"Own {frappe.generate_hash()[:6]}",
                "campaign_type": "Other",
                "status": "Active",
                "start_date": frappe.utils.today(),
            }
        ).insert()
        self.track_doc("Donation Campaign", campaign.name)
        campaign.db_set("owner", user, update_modified=False)
        stored = frappe.get_doc({"doctype": "Donation Campaign", "name": campaign.name, "owner": user})
        self.assertTrue(frappe.has_permission("Donation Campaign", "read", doc=stored, user=user))
        self.assertTrue(frappe.has_permission("Donation Campaign", "read", doc=campaign.name, user=user))

    def test_a_member_can_still_create_their_own_amendment_request(self):
        """Control: `create` of a not-yet-stored doc (owner set by insert) is the legitimate case the
        guard must let through; Contribution Amendment Request grants create to Verenigingen Member
        with if_owner."""
        email = f"creator-{frappe.generate_hash()[:8]}@test.invalid"
        user = self.create_test_user(email, roles=["Verenigingen Member"]).name
        new = frappe.new_doc("Contribution Amendment Request")
        new.owner = user
        self.assertTrue(frappe.has_permission("Contribution Amendment Request", "create", doc=new, user=user))

    def test_an_unsaved_doc_owned_by_the_caller_is_refused_for_read(self):
        """Pins the deliberate change: an unsaved doc claiming the caller as owner is False for any
        ptype but `create` (it was True, which is the forged-owner hole). Mutant: with the guard's
        `return` forced True this assertion reddens."""
        email = f"unsaved-{frappe.generate_hash()[:8]}@test.invalid"
        user = self.create_test_user(email, roles=["Verenigingen Volunteer"]).name
        new = frappe.new_doc("Donation Campaign")
        new.owner = user
        self.assertFalse(frappe.has_permission("Donation Campaign", "read", doc=new, user=user))
