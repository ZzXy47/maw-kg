#!/usr/bin/env python3
"""P1 verification battery — every v3.1 P1 acceptance criterion, actually executed.

1. MCP serve: initialize + tools/list shows exactly the 8 maw_* tools
2. Each tool class fires once against real data (explore/query/node/impact on android)
3. Budget: maxChars caps a 20K-char explore at 8K
4. G0-①②: stale lock auto-clean — plant a fake dead-pid writer.lock, verify cleaned
5. G0-④: retry path exists (unit: monkeypatch subprocess.run to fail twice then pass)
6. ENV: cluster check reports E: repos on 4MB clusters
7. FP probe (v3.1 P1-④): maw_explore for a nonexistent symbol returns empty/no fabrication
8. Contract tools through MCP: maw_contracts + maw_contract_check + maw_cross_impact
9. Version stamps exposed via maw_status
"""
import json, subprocess, sys, time, os, ctypes
from pathlib import Path

MAW = Path(r"D:/maw-kg")
SRV = MAW / "src" / "mcp_server.py"
results = []

def chk(name, ok, detail=""):
    results.append({"name": name, "pass": bool(ok), "detail": str(detail)[:220]})
    print(("PASS" if ok else "FAIL"), name, "|", str(detail)[:150])

# --- launch server
p = subprocess.Popen([sys.executable, str(SRV), "serve"], stdin=subprocess.PIPE,
                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
import threading, queue as Q
q = Q.Queue()
def rd():
    for line in p.stdout: q.put(line)
threading.Thread(target=rd, daemon=True).start()
iid = [0]
def send(obj):
    p.stdin.write((json.dumps(obj)+"\n").encode()); p.stdin.flush()
def recv(t=90):
    try: return json.loads(q.get(timeout=t))
    except Q.Empty: return None
def call(name, args, t=90):
    iid[0]+=1
    send({"jsonrpc":"2.0","id":iid[0],"method":"tools/call","params":{"name":name,"arguments":args}})
    r = recv(t)
    if not r or "result" not in r:
        return None, r
    txt = r["result"]["content"][0].get("text", "")
    err = r["result"].get("isError", False)
    return (None if err else txt), (txt if err else None)

send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"p1v","version":"1"}}})
init=recv(); chk("1a init handshake", init and "maw-kg" in json.dumps(init))
send({"jsonrpc":"2.0","method":"notifications/initialized"})
send({"jsonrpc":"2.0","id":2,"method":"tools/list"})
tl=recv()
tlist = tl.get("result",{}).get("tools") if isinstance(tl,dict) else None
tools=[t["name"] for t in tlist] if tlist else []
chk("1b eight tools listed", len(tools)==8 and all(t.startswith("maw_") for t in tools), tools)

# 2 — live tool calls
t0=time.time(); out,_=call("maw_explore",{"query":"registerDevice flow","repo":"ha-android"}); dt=time.time()-t0
chk("2a maw_explore works", out and "registerDevice" in out, f"{dt:.1f}s {len(out or '')}ch")
out2,_=call("maw_query",{"query":"RegistrationsView","repo":"ha-core"})
chk("2b maw_query works", out2 and "RegistrationsView" in out2)
out3,err3=call("maw_node",{"name":"register","repo":"ha-ios","file":"Sources/Shared/API/HAAPI.swift"})
chk("2c maw_node works", out3 and "register" in out3)
out4,_=call("maw_impact",{"symbol":"registerDevice","repo":"ha-android"})
chk("2d maw_impact works", out4 and ("affected" in out4.lower() or "impact" in out4.lower()))

# 3 — budget
out5,_=call("maw_explore",{"query":"websocket authentication","repo":"ha-ios","maxChars":8192})
chk("3 maxChars budget caps ~20K explore", out5 is not None and len(out5)<=8300, f"{len(out5 or '')}ch")

# 4 — stale lock auto-clean (G0-①②)
core_lock = Path(r"E:/CrossDevice_Agent_GitNexus_Pilot/repos/home-assistant-core/.codegraph/writer.pid")
bak = None
if core_lock.exists():
    bak = core_lock.read_bytes(); core_lock.unlink()
core_lock.parent.mkdir(parents=True, exist_ok=True)
core_lock.write_text(json.dumps({"pid": 99999999, "mode":"fallback","startedAt":0,"ready":True}), encoding="utf-8")
gov = subprocess.run([sys.executable, str(SRV), "gov"], capture_output=True, text=True)
cleaned = '"state": "stale-cleaned"' in gov.stdout and "99999999" in gov.stdout
if core_lock.exists():
    core_lock.unlink()
if bak: core_lock.write_bytes(bak)
chk("4 stale lock auto-cleaned (dead pid 99999999)", cleaned, gov.stdout[:120])

# 5 — retry logic (unit)
sys.path.insert(0, str(MAW/"src"))
import mcp_server as MS
calls = {"n": 0}
def fake_run(*a, **k):
    class R:
        pass
    r = R()
    r.returncode = 1 if calls["n"] < 2 else 0
    r.stdout = "ok" if calls["n"] >= 2 else ""
    r.stderr = ""
    calls["n"] += 1
    return r
orig_run = MS.subprocess.run
MS.subprocess.run = fake_run
try:
    got = MS.cg_cli(["x"], Path("."))
    retried = calls["n"] == 3
except Exception:
    retried = False
finally:
    MS.subprocess.run = orig_run
chk("5 G0-④ retry: 2 transient failures then success", retried, f"attempts={calls['n']}")

# 6 — env cluster check
env = subprocess.run([sys.executable, str(SRV), "env"], capture_output=True, text=True)
chk("6 env selfcheck flags 4MB clusters", "4194304" in env.stdout or "4096" in env.stdout, env.stdout[:150])

# 7 — FP probe: CG explore fabricates results for garbage queries (returns unrelated symbols as "Found N").
# MAW-KG principle #3: maw_explore must REFUSE to fabricate. Implemented at the tool layer: if the
# literal query terms never appear in the FTS index AND no exact symbol match exists → return empty result.
out7, err7 = call("maw_explore", {"query": "ZzNotARealSymbolXyzzy", "repo": "ha-android"})
fabricated = out7 and "ZzNotARealSymbolXyzzy" in out7 and "Found" in out7
chk("7 FP probe: no fabricated hits", not fabricated, (out7 or err7 or "")[:120])

# 8 — contract tools via MCP
out8,_=call("maw_contracts",{})
chk("8a maw_contracts lists 3", out8 and "3 contracts" in out8)
out9,err9=call("maw_contract_check",{})
d9 = json.loads(out9) if out9 else {}
chk("8b maw_contract_check ok", d9.get("ok") and d9.get("fail")==0, f"fail={d9.get('fail')}")
out10,_=call("maw_cross_impact",{"repo":"ha-core","symbol":"RegistrationsView.post"})
d10 = json.loads(out10) if out10 else {}
cross = d10.get("cross_impacts", [])
chk("8c cross_impact reaches 2 contracts", len(cross)>=2, [c.get("contract") for c in cross])

# 9 — status exposes versions
out11,_=call("maw_status",{})
d11 = json.loads(out11) if out11 else {}
idx = d11.get("indexes", {})
chk("9 status shows extraction versions", any(v.get("extraction") for v in idx.values() if isinstance(v,dict)), list(idx)[:3])

# shutdown (G0-③ exercised by server exit)
p.terminate(); p.wait(10)

ok = all(r["pass"] for r in results)
out = MAW/"tests"/"p1-verification.json"
out.write_text(json.dumps({"phase":"P1","all_pass":ok,"results":results},ensure_ascii=False,indent=2),encoding="utf-8")
print("\nP1 VERIFICATION:", "ALL PASS" if ok else "FAILURES PRESENT", f"({sum(r['pass'] for r in results)}/{len(results)})")
sys.exit(0 if ok else 1)
