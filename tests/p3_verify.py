#!/usr/bin/env python3
"""P3 verification — run all six extractors against the REAL fixture files,
then the red-light script assertions must turn GREEN through the extractor path."""
import json, sys, subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from extractors import (py_class_route, kt_url_builder, kt_retrofit_url,
                        sw_request_wrapper, sw_array_path, path_norm, read)
results = []
def chk(name, ok, detail=""):
    results.append({"name": name, "pass": bool(ok), "detail": str(detail)[:180]})
    print(("PASS" if ok else "FAIL"), name, "|", str(detail)[:140])

import os as _os
P = Path(_os.environ.get("MAW_KG_TEST_REPOS", "repos"))

# PY-CLASS-ROUTE
src = read(P/"home-assistant-core/homeassistant/components/mobile_app/http_api.py")
eps = py_class_route(src, "http_api.py")
chk("1 PY-CLASS-ROUTE finds POST /api/mobile_app/registrations",
    any(e.method=="POST" and e.path=="/api/mobile_app/registrations" for e in eps), eps[:2])

# KT-URL-BUILDER
src = read(P/"home-assistant-android/common/src/main/kotlin/io/homeassistant/companion/android/common/data/integration/impl/IntegrationRepositoryImpl.kt")
eps = kt_url_builder(src, "IntegrationRepositoryImpl.kt")
chk("2 KT-URL-BUILDER finds /api/mobile_app/registrations",
    any(e.path=="/api/mobile_app/registrations" for e in eps), eps[:2])

# KT-RETROFIT-URL (verb source)
eps = kt_retrofit_url(src, "IntegrationService.kt")
svc = read(P/"home-assistant-android/common/src/main/kotlin/io/homeassistant/companion/android/common/data/integration/impl/IntegrationService.kt")
retro = kt_retrofit_url(svc, "IntegrationService.kt")
reg = [r for r in retro if r["fun"]=="registerDevice"]
chk("3 KT-RETROFIT-URL: registerDevice verb=POST + @Url", bool(reg) and reg[0]["verb"]=="POST" and reg[0]["has_url_param"], reg[:1])

# SW-REQUEST-WRAPPER
src = read(P/"home-assistant-ios/Sources/Shared/API/HAAPI.swift")
eps = sw_request_wrapper(src, "HAAPI.swift")
chk("4 SW-REQUEST-WRAPPER finds POST /mobile_app/registrations",
    any(e.method=="POST" and e.path=="/mobile_app/registrations" for e in eps), eps[:2])

# SW-ARRAY-PATH
src = read(P/"home-assistant-ios/Sources/Shared/Watch/DeviceRegistration/WatchDeviceRegistrar.swift")
eps = sw_array_path(src, "WatchDeviceRegistrar.swift")
chk("5 SW-ARRAY-PATH finds /mobile_app/registrations",
    any("/mobile_app/registrations" in e.path for e in eps), eps[:3])

# PATH-NORM
chk("6a PATH-NORM: /api/x == /x", path_norm("/api/mobile_app/registrations", "/mobile_app/registrations"))
chk("6b PATH-NORM: /api/web_hook/{id} == /api/web_hook/{webhook_id}",
    path_norm("/api/web_hook/{webhook_id}", "/api/web_hook/{id}"))
chk("6c PATH-NORM negative: /other != /x", not path_norm("/api/other", "/x"))

# Integration: extractors → contract auto-discovery for the pilot endpoint
core_eps = py_class_route(read(P/"home-assistant-core/homeassistant/components/mobile_app/http_api.py"), "core")
kt_eps = kt_url_builder(read(P/"home-assistant-android/common/src/main/kotlin/io/homeassistant/companion/android/common/data/integration/impl/IntegrationRepositoryImpl.kt"), "android")
sw_eps = sw_request_wrapper(read(P/"home-assistant-ios/Sources/Shared/API/HAAPI.swift"), "ios")
provider = [e for e in core_eps if path_norm(e.path, "/api/mobile_app/registrations")]
cons = [e for e in kt_eps + sw_eps if path_norm(e.path, "/api/mobile_app/registrations")]
chk("7 INTEGRATION: provider+2 consumers auto-discovered via extractors+PATH-NORM",
    len(provider)>=1 and len(cons)>=2, f"provider={len(provider)} consumers={len(cons)}")

ok = all(r["pass"] for r in results)
out = Path(__file__).parent / "p3-verification.json"
out.write_text(json.dumps({"phase":"P3","all_pass":ok,"results":results},ensure_ascii=False,indent=2),encoding="utf-8")
print("\nP3 VERIFICATION:", "ALL PASS" if ok else "FAILURES", f"({sum(r['pass'] for r in results)}/{len(results)})")
sys.exit(0 if ok else 1)
