#!/usr/bin/env python3
"""O-1..O-5 acceptance: new tools + prewarm latency, measured over the MCP wire."""
import json, subprocess, sys, threading, time
import queue as Q
from pathlib import Path

MAW = Path(r'D:/maw-kg')
results = []
def chk(name, ok, detail=""):
    results.append({"name": name, "pass": bool(ok), "detail": str(detail)[:200]})
    print(("PASS" if ok else "FAIL"), name, "|", str(detail)[:140])

p = subprocess.Popen([sys.executable, str(MAW/'src/mcp_server.py'), 'serve'],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
q = Q.Queue()
threading.Thread(target=lambda: [q.put(l) for l in p.stdout], daemon=True).start()
iid = [0]
def send(o):
    p.stdin.write((json.dumps(o)+'\n').encode()); p.stdin.flush()
def recv(t=120):
    try: return json.loads(q.get(timeout=t))
    except Q.Empty: return None
def call(name, args, t=120):
    iid[0] += 1
    send({'jsonrpc':'2.0','id':iid[0],'method':'tools/call','params':{'name':name,'arguments':args}})
    return recv(t)

t0 = time.time()
send({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'o-test','version':'1'}}})
recv()
send({'jsonrpc':'2.0','method':'notifications/initialized'})
# wait for prewarm to take effect (daemon handshake ~2-4s)
time.sleep(4)

# 1 — ten tools listed
send({'jsonrpc':'2.0','id':2,'method':'tools/list'})
tl = recv()
tools = [t['name'] for t in tl['result']['tools']] if tl else []
chk('1 ten tools (8+2 new)', len(tools)==10 and 'maw_cognition_search' in tools and 'maw_detect_changes' in tools, tools)

# 2 — O-1 prewarm: first maw_explore latency after initialize+4s
t1 = time.time()
r = call('maw_explore', {'query':'registerDevice flow','repo':'ha-android'})
dt = time.time()-t1
ok = r and 'result' in r and 'registerDevice' in json.dumps(r)
chk('2 O-1 prewarm first-explore <10s', ok and dt < 10, f"{dt:.1f}s (was 22.8s cold)")

# 3 — second explore even faster (daemon warm)
t2 = time.time()
r = call('maw_explore', {'query':'WebhookRegistry','repo':'ha-core'})
dt2 = time.time()-t2
chk('3 warm explore <10s', r and 'result' in r and dt2 < 10, f"{dt2:.1f}s")

# 4 — O-3 cognition search over MCP
r = call('maw_cognition_search', {'keyword':'webhook'})
d = json.loads(r['result']['content'][0]['text'])
chk('4 O-3 cognition_search', len(d['results'])>=1, [x['contract'] for x in d['results']])

# 5 — O-3 tag search
r = call('maw_cognition_search', {'tag':'EG6S'})
d = json.loads(r['result']['content'][0]['text'])
chk('5 O-3 tag search', any(x['contract']=='mobile-app-watch-registration' for x in d['results']), [x['contract'] for x in d['results']])

# 6 — O-3 empty query rejected
r = call('maw_cognition_search', {})
d = json.loads(r['result']['content'][0]['text'])
chk('6 O-3 empty query → error (no fabrication)', 'error' in d, d)

# 7 — O-2 detect_changes over MCP (clean tree → empty, honest)
r = call('maw_detect_changes', {'repo':'ha-android'})
d = json.loads(r['result']['content'][0]['text'])
chk('7 O-2 clean tree → 0 symbols 0 hits', d['changed_files']==0 and d['changed_symbols']==[], d)

# 8 — O-2 with a probe edit: symbol + contract hit through the MCP wire
repo = Path(r'E:/CrossDevice_Agent_GitNexus_Pilot/repos/home-assistant-android')
f = repo/'common/src/main/kotlin/io/homeassistant/companion/android/common/data/integration/impl/IntegrationRepositoryImpl.kt'
orig = f.read_text(encoding='utf-8')
try:
    f.write_text(orig + '\nfun o5ProbeFn(): Int = 42\n', encoding='utf-8')
    r = call('maw_detect_changes', {'repo':'ha-android'})
    d = json.loads(r['result']['content'][0]['text'])
    syms = [s['symbol'] for s in d['changed_symbols']]
    chk('8 O-2 probe → symbol mapped, no false contract', 'o5ProbeFn' in syms and d['contract_hits']==[], f"syms={syms[:3]} hits={d['contract_hits']}")
finally:
    f.write_text(orig, encoding='utf-8')
    subprocess.run(['git','-C',str(repo),'checkout','--',str(f)],capture_output=True)

p.terminate()

out = MAW/'tests/o-fix-acceptance.json'
out.write_text(json.dumps({'all_pass': all(x['pass'] for x in results), 'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')
n = sum(1 for x in results if x['pass'])
print(f"\nO-ROUND ACCEPTANCE: {n}/{len(results)}")
sys.exit(0 if n==len(results) else 1)
