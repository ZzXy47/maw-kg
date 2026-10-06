#!/usr/bin/env python3
"""P4 verification — L4 cognition alignment + drift detection.

1. Full alignment: 3 contracts, 3 entries → coverage 1.0, governance=aligned
2. Partial authoring: remove 1 entry → coverage 0.67, state=partial (NOT a red flag)
3. Drift: Stale detection — corrupt recorded hash → stale flagged
4. Drift: Orphan detection — entry for unregistered contract → orphan flagged
5. Restore → aligned again
"""
import json, sys, shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import cognition

results = []
def chk(name, ok, detail=""):
    results.append({"name": name, "pass": bool(ok), "detail": str(detail)[:160]})
    print(("PASS" if ok else "FAIL"), name, "|", str(detail)[:130])

COG = Path(r"D:/maw-kg/contracts/cognition.yaml")
bak = COG.read_bytes()

# 1 full alignment
r = cognition.run()
chk("1 full alignment (3/3)", r["coverage"]==1.0 and r["governance_state"]=="aligned", r)

# 2 partial authoring
import yaml
d = yaml.safe_load(COG.read_text(encoding="utf-8"))
removed = d["contracts"].pop("mobile-app-webhook-update")
COG.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
r = cognition.run()
chk("2 partial authoring → coverage 0.67, state=partial (NOT red)",
    r["coverage"]==0.67 and r["governance_state"]=="partial" and r["drift"]["missing"]==["mobile-app-webhook-update"], r)

# 3 stale drift
d = yaml.safe_load(COG.read_text(encoding="utf-8"))
d["contracts"]["mobile-app-registration"]["provider_sha256"] = "0"*64
COG.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
r = cognition.run()
chk("3 stale drift flagged (hash mismatch)", any(s["contract"]=="mobile-app-registration" for s in r["drift"]["stale"]), r["drift"]["stale"])

# 4 orphan drift
d["contracts"]["ghost-contract"] = {"tag":"EG1S","entry":"ghost[EG1S]: F:x | R: | A:y | S:z"}
COG.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
r = cognition.run()
chk("4 orphan drift flagged", r["drift"]["orphan"]==["ghost-contract"], r["drift"]["orphan"])

# 5 restore
COG.write_bytes(bak)
r = cognition.run()
chk("5 restore → aligned again", r["governance_state"]=="aligned", r["governance_state"])

ok = all(x["pass"] for x in results)
out = Path(__file__).parent / "p4-verification.json"
out.write_text(json.dumps({"phase":"P4","all_pass":ok,"results":results},ensure_ascii=False,indent=2),encoding="utf-8")
print("\nP4 VERIFICATION:", "ALL PASS" if ok else "FAILURES", f"({sum(x['pass'] for x in results)}/{len(results)})")
sys.exit(0 if ok else 1)
