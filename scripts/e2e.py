"""End-to-end smoke test against a running stack (API + mock providers).

    python scripts/e2e.py [persona ...] [--api http://localhost:8000]

Signs in as the demo operator, runs each persona, and drives it to a terminal outcome the way a human would
(applying the sample fix, approving reviews, retrying provisioning). Exits non-zero if an expectation fails."""

import argparse
import sys
import time

import httpx

EXPECT = {  # persona -> final status and key events that must appear in the audit trail
    "happy_path": ("LIVE", ["callback_duplicate_ignored"]),
    "gst_cancelled": ("LIVE", ["merchant_responded"]),
    "blurred_document": ("LIVE", ["merchant_responded"]),
    "name_mismatch": ("LIVE", ["review_decision"]),
    "duplicate": ("LIVE", ["review_decision"]),
    "high_risk_mid_failure": ("LIVE", ["mid_attempt_failed", "provisioning_retry_requested"]),
    "late_callback": ("LIVE", ["check_timed_out", "callback_stale_ignored"]),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("personas", nargs="*", default=list(EXPECT))
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()
    c = httpx.Client(base_url=args.api, timeout=90)

    def token(role):
        r = c.post("/auth/demo", json={"role": role})
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    ops, merchant = token("operator"), token("merchant")
    failures = 0
    for key in args.personas:
        app = c.post(f"/demo/personas/{key}/run", headers=ops).raise_for_status().json()
        app_id = app["id"]
        print(f"\n▶ {key}  {app['reference']}")
        last, deadline, acted = None, time.time() + args.timeout, set()
        detail = {}
        while time.time() < deadline:
            detail = c.get(f"/ops/applications/{app_id}", headers=ops).raise_for_status().json()
            status = detail["application"]["status"]
            if status != last:
                print(f"   {time.strftime('%H:%M:%S')}  {status:22} waiting_for={detail.get('waiting_for')}")
                last = status
            if status in ("LIVE", "REJECTED", "WITHDRAWN"):
                actions = {a["action"] for a in detail.get("audit", [])}
                if all(e in actions for e in EXPECT.get(key, ("", []))[1]):
                    break  # some events (e.g. a late callback) can arrive after go-live
            if status == "AWAITING_MERCHANT" and detail.get("waiting_for") == "merchant" and "fix" not in acted:
                r = c.post(f"/demo/applications/{app_id}/apply-fix", headers=merchant)
                print(f"   merchant applies sample fix -> {r.status_code}")
                acted.add("fix")
            if status == "MANUAL_REVIEW" and detail.get("waiting_for") == "review":
                r = c.post(f"/ops/applications/{app_id}/decision", headers=ops,
                           json={"decision": "approve", "note": "Verified manually in e2e test"})
                if r.status_code == 200:
                    print("   operator approves")
            if status == "PROVISIONING_FAILED" and detail.get("waiting_for") == "ops" and "retry" not in acted:
                c.post(f"/ops/applications/{app_id}/retry-provisioning", headers=ops).raise_for_status()
                print("   operator retries provisioning")
                acted.add("retry")
            time.sleep(2)
        want_status, want_events = EXPECT.get(key, ("LIVE", []))
        actions = {a["action"] for a in detail.get("audit", [])}
        missing = [e for e in want_events if e not in actions]
        ok = detail["application"]["status"] == want_status and not missing
        chain = detail.get("audit_chain", {})
        print(f"   {'PASS' if ok else 'FAIL'}  status={detail['application']['status']} mid={detail['application']['mid']}"
              f" audit_chain_valid={chain.get('valid')} entries={chain.get('entries')}"
              + (f" missing_events={missing}" if missing else ""))
        failures += 0 if ok else 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
