"""MAW-KG P3 — HTTP contract extractors (six forms, v3.1 §7).

These run on the CodeGraph sqlite indexes (nodes carry source context via
signature/docstring where present) plus raw source files — a deterministic
scanner that recognizes the three framework forms GitNexus missed, per the
root-cause chain. Each extractor is pure: source text in, endpoint tuples out.

Extractors:
  PY-CLASS-ROUTE   HomeAssistantView class-attribute url + verb method
  KT-URL-BUILDER   HttpUrl.Builder().addPathSegments(...) chains
  KT-RETROFIT-URL  @POST/@GET suspend fun f(@Url url: HttpUrl) — verb source
  SW-REQUEST-WRAPPER  request(path: "x", method: .post) wrappers
  SW-ARRAY-PATH    path: ["mobile_app","registrations"] + method enum
  PATH-NORM        /api prefix equivalence
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Endpoint:
    method: str      # GET/POST/...
    path: str        # normalized "/api/..." form
    symbol: str      # enclosing symbol best-effort
    file: str
    line: int
    role: str        # provider|consumer
    source: str      # extractor name


# ---------------------------------------------------------------- helpers
def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- PY-CLASS-ROUTE
def py_class_route(src: str, file: str) -> list:
    """class X(HomeAssistantView):  url = "/path"  + async def post(...)."""
    out = []
    for m in re.finditer(
        r"class\s+(\w+)\s*\([^)]*HomeAssistantView[^)]*\):"
        r"(.*?)(?=\nclass\s|\Z)", src, re.S):
        cls, body = m.group(1), m.group(2)
        um = re.search(r"url\s*=\s*[\"']([^\"']+)[\"']", body)
        if not um:
            continue
        url = um.group(1)
        for verb in re.finditer(r"async\s+def\s+(get|post|put|delete|patch)\s*\(", body):
            line = src[: m.start() + verb.start(1)].count("\n") + 1
            out.append(Endpoint("POST" if verb.group(1) == "post" else verb.group(1).upper(),
                                url, f"{cls}.{verb.group(1)}", file, line, "provider",
                                "PY-CLASS-ROUTE"))
    return out


# ---------------------------------------------------------------- KT-URL-BUILDER
def kt_url_builder(src: str, file: str) -> list:
    """url.newBuilder().addPathSegments("api/x/...").build()"""
    out = []
    for m in re.finditer(
        r"(\w+)\.newBuilder\(\)\s*\.\s*addPathSegments\(\s*\"([^\"]+)\"\s*\)",
        src):
        line = src[: m.start()].count("\n") + 1
        path = "/" + m.group(2).lstrip("/")
        out.append(Endpoint("", path, m.group(1), file, line, "consumer", "KT-URL-BUILDER"))
    return out


# ---------------------------------------------------------------- KT-RETROFIT-URL
def kt_retrofit_url(src: str, file: str) -> list:
    """@POST (or @GET etc.) suspend fun name(@Url url: HttpUrl, ...) — the verb
    source for builder chains passed to Retrofit @Url methods."""
    out = []
    for m in re.finditer(
        r"@(GET|POST|PUT|DELETE|PATCH)\b[^\n]*\n\s*(?:suspend\s+)?fun\s+(\w+)\s*\(([^)]*)\)",
        src):
        verb, fun, params = m.group(1), m.group(2), m.group(3)
        has_url = "@Url" in params
        line = src[: m.start()].count("\n") + 1
        out.append({"verb": verb, "fun": fun, "has_url_param": has_url,
                    "line": line, "file": file, "extractor": "KT-RETROFIT-URL"})
    return out


# ---------------------------------------------------------------- SW-REQUEST-WRAPPER
def sw_request_wrapper(src: str, file: str) -> list:
    """request( path: "mobile_app/registrations", ... method: .post )
    Window bounded to 200 chars between path: and method: so the pair must be
    in the same call — prevents cross-call (path, method) marriages."""
    out = []
    for m in re.finditer(
        r"request\(\s*path:\s*\"([^\"]+)\"\s*,(?:(?!request\().){0,220}?method:\s*\.(\w+)",
        src, re.S):
        line = src[: m.start()].count("\n") + 1
        path = "/" + m.group(1).lstrip("/")
        out.append(Endpoint(m.group(2).upper(), path, "request-wrapper", file, line,
                            "consumer", "SW-REQUEST-WRAPPER"))
    return out


# ---------------------------------------------------------------- SW-ARRAY-PATH
def sw_array_path(src: str, file: str) -> list:
    """sendForJSON( ... method: .post, path: ["mobile_app","registrations"])"""
    out = []
    for m in re.finditer(
        r"path:\s*\[\s*\"([^\"]+)\"\s*,\s*\"([^\"]+)\"[^\]]*\]\s*,?\s*\n?\s*body:\s*body",
        src):
        line = src[: m.start()].count("\n") + 1
        path = "/" + "/".join([m.group(1), m.group(2)]).lstrip("/")
        out.append(Endpoint("", path, "array-path", file, line, "consumer", "SW-ARRAY-PATH"))
    # also catch (method:.post, path:[...]) ordering variants
    for m in re.finditer(
        r"method:\s*\.(\w+)[^)]*?path:\s*\[\s*\"([^\"]+)\"\s*,\s*\"([^\"]+)\"",
        src, re.S):
        line = src[: m.start()].count("\n") + 1
        path = "/" + "/".join([m.group(2), m.group(3)]).lstrip("/")
        out.append(Endpoint(m.group(1).upper(), path, "array-path", file, line,
                            "consumer", "SW-ARRAY-PATH"))
    return out


# ---------------------------------------------------------------- PATH-NORM
def path_norm(a: str, b: str) -> bool:
    """Equivalence under /api prefix delta + webhook placeholder unification."""
    def norm(s):
        s = s.strip()
        if not s.startswith("/"):
            s = "/" + s
        s = re.sub(r"\{webhook_?id\}", "{id}", s, flags=re.I)
        s = re.sub(r"/api(?=/)", "", s)  # strip leading /api when followed by /
        return s.strip("/").lower()
    return norm(a) == norm(b)


# ---------------------------------------------------------------- runner
def scan_repo(repo_root: Path) -> list:
    eps = []
    for p in repo_root.rglob("*"):
        if not p.is_file():
            continue
        rel = str(p).replace("\\", "/")
        if any(x in rel for x in ("/.git/", "/.codegraph/", "/.aoci/", "node_modules")):
            continue
        try:
            if p.suffix == ".py":
                src = read(p)
                eps += py_class_route(src, rel)
            elif p.suffix in (".kt", ".kts"):
                src = read(p)
                eps += kt_url_builder(src, rel)
            elif p.suffix == ".swift":
                src = read(p)
                eps += sw_request_wrapper(src, rel)
                eps += sw_array_path(src, rel)
        except Exception:
            continue
    return eps
