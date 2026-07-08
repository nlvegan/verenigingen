# False-Confidence Remediation — Roadmap

Design: ./2026-07-08-false-confidence-remediation-design.md
Worklist: ../test-inventory/ (37 reports; each names offenders per file)

## Module sequence (risk-ordered; executed in waves of 3)
Wave 1: 1 SEPA · 2 Payments (mollie/ing/ponto) · 3 Billing/dues/fee
Wave 2: 4 Member-financial & history · 5 e_boekhouden · 6 Membership/termination
Wave 3: 7 Chapter/volunteer/donation/donor · 8 Report/api/portal · 9 Utils/infra/security
Wave 4: 10 Co-located doctype controllers + mijnrood_sync

## Module Remediation Cycle (run per module — see plan Task template)
1. Snapshot baseline module coverage.
2. Grep the machine-detectable patterns + read the inventory-named offenders; confirm each flag.
3. Disposition each: live→rewrite, dead→delete+log dead-code, missing→delete+log missing-coverage.
4. Mutation-verify every rewrite (green→break→red→revert).
5. Re-run the module suite green on a test_site_N.
6. Confirm coverage-Δ ≥ 0 vs. baseline; if a deletion dropped coverage, add an offsetting real test.
7. Update TRACKER + backlogs; commit `test(<module>): remediate false-confidence tests`.

## Grep patterns (step 2)
assertIsNotNone(result.success) · assertTrue(True) · if result["success"]: · try:/except: pass ·
0 `def test_` under a TestCase · @unittest.skip clusters · isinstance(...) as sole assertion ·
module-level print( with no assert.
