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


# ---------------------------------------------------------------- TS-KOA-ROUTE
def ts_koa_route(src: str, file: str) -> list:
    """const r = new Router(); r.get('/api/x/:id', mw, ctrl.h) — Koa Router
    chained route registration (ekko-studio server modules pattern)."""
    out = []
    for m in re.finditer(
        r"(\w+)\.(get|post|put|patch|delete)\(\s*[\"']([^\"']+)[\"']\s*,"
        r"(?:(?!/api/).){0,400}?(\w+)\.(\w+)\)",
        src, re.S):
        router_var, verb, path, ctrl_ns, handler = m.groups()
        # only Koa router files: require the new Router() + path starts with /api/ or /
        if "new Router()" not in src:
            continue
        line = src[: m.start()].count("\n") + 1
        out.append(Endpoint(m.group(2).upper(), m.group(3),
                            f"{ctrl_ns}.{handler}", file, line, "provider",
                            "TS-KOA-ROUTE"))
    return out


# ---------------------------------------------------------------- TS-REQUEST-TEMPLATE
TS_REQUEST_RE = re.compile(
    r"(?:await\s+)?request(?:<[^>]*>)?\(\s*"
    r"([\"'`])([^\"'`]*\{[^\"'`}]*)?\1?\s*,?\s*"
    r"(?:\{[^}]*(?:method:\s*[\"'](\w+)[\"'])[^}]*\})?",
    re.S)


def _clean_ts_path(raw: str) -> str:
    """Normalize a TS client path literal to a comparable route path.
    Ternary/nested-backtick chunks = query conditional → strip; bare query-ish
    identifiers (${suffix}/${qs}/${params}) = query → strip; ?${x} = query tail
    → strip; every other ${x} (calls, member exprs) = path param → {param};
    glued ?literal → cut."""
    p = raw
    if re.search(r"\$\{[^}]*\?", p) or "`" in p:
        p = re.sub(r"\$\{.*$", "", p)
    else:
        def repl(m):
            expr = m.group(1).strip()
            if re.fullmatch(r"[a-z_]\w*", expr) and expr.lower() in (
                    "suffix", "qs", "query", "params", "querystring", "q", "search"):
                return ""
            return "{param}"
        p = re.sub(r"\$\{([^}]*)\}", repl, p)
    return p.split("?")[0]


def ts_request_template(src: str, file: str) -> list:
    """request<T>(`/api/x/${id}`, { method: 'PATCH', ... }) — client API wrapper.
    Path params may be template literals; method defaults to GET."""
    out = []
    pat = (r"request(?:<[^>]*(?:<[^>]*>)?[^>]*>)?\(\s*[\"'`]([^\"'`]+)[\"'`]"
           r"(?:\s*,\s*\{(?:(?!\}\)).)*?method:\s*[\"'](\w+)[\"'])?")
    for m in re.finditer(pat, src, re.S):
        raw_path, verb = m.group(1), m.group(2) or "GET"  # omitted method = GET
        path = _clean_ts_path(raw_path)
        line = src[: m.start()].count("\n") + 1
        out.append(Endpoint(verb.upper(), "/" + path.lstrip("/"), "request-wrapper",
                            file, line, "consumer", "TS-REQUEST-TEMPLATE"))
    # appendQuery('path', params) / withQuery(...) helpers — GET semantics
    for m in re.finditer(
        r"(?:appendQuery|withQuery|buildQuery)\(\s*[\"'`]([^\"'`]+)[\"'`]", src):
        raw_path = m.group(1)
        if not raw_path.startswith("/"):  # only absolute API paths
            continue
        # statement-scan: search for method: within the rest of this statement
        # (paren-walk alone stops at appendQuery's own closing paren)
        i, depth = m.end(), 1
        while i < len(src) and depth > 0:
            if src[i] == '(':
                depth += 1
            elif src[i] == ')':
                depth -= 1
            i += 1
        window = src[m.end():i + 400]
        vm = re.search(r"method:\s*[\"'](\w+)[\"']", window.split("\n\n")[0])
        v = (vm.group(1) if vm else "GET").upper()
        path = _clean_ts_path(raw_path)
        line = src[: m.start()].count("\n") + 1
        out.append(Endpoint(v, "/" + path.lstrip("/"), "query-helper",
                            file, line, "consumer", "TS-REQUEST-TEMPLATE"))
    # path-builder indirection: const p = (id) => `/api/x/${id}` then
    # request(p(...), { method: 'DELETE' }) or request(p(...) + '/suffix', ...)
    # Resolve the builder literal into a consumer call, with method lookahead.
    builders = {}
    for m in re.finditer(
        r"(?:const|let|function)\s+(\w+Path)\s*(?:=\s*(?:\([^)]*\)|\w+)\s*=>|=?\s*function\s*\([^)]*\)\s*|\([^)]*\)\s*=>)\s*[\"'`]([^\"'`]+)[\"'`]",
        src):
        builders[m.group(1)] = m.group(2)
    for m in re.finditer(
        r"request(?:<[^>]*(?:<[^>]*>)?[^>]*>)?\(\s*(\w+Path)\s*\(", src):
        name = m.group(1)
        if name not in builders:
            continue
        # paren-depth walk: m.end() sits just inside presetPath's '('.
        i, depth = m.end(), 1
        while i < len(src) and depth > 0:
            if src[i] == '(':
                depth += 1
            elif src[i] == ')':
                depth -= 1
            i += 1
        inner_close = i  # just past presetPath(...)
        # continue to the matching ')' of the enclosing request(...) call
        depth = 1
        j = inner_close
        while j < len(src) and depth > 0:
            if src[j] == '(':
                depth += 1
            elif src[j] == ')':
                depth -= 1
            j += 1
        outer_close = j
        window = src[m.end():outer_close]           # args region of request()
        cm = re.search(r"\)\s*\+\s*[\"']([^\"']+)[\"']", window)
        vm = re.search(r"method:\s*[\"'](\w+)[\"']", window)
        raw_path = builders[name] + (cm.group(1) if cm else "")
        v = (vm.group(1) if vm else "GET").upper()
        path = _clean_ts_path(raw_path)
        line = src[: m.start()].count("\n") + 1
        out.append(Endpoint(v, "/" + path.lstrip("/"), "path-builder",
                            file, line, "consumer", "TS-REQUEST-TEMPLATE"))
    # fetch() calls (file uploads/downloads bypassing request()): fetch(url)
    # and fetch(`${baseUrl}/api/...`, { method: 'POST' })
    for m in re.finditer(
        r"(?:await\s+|return\s+|=)?fetch\(\s*(?:[\"'`]([^\"'`]+)[\"'`]|\$\{[^}]+\}([\"'`][^\"'`]+)[\"'`])",
        src):
        raw_path = m.group(1) or m.group(2) or ""
        if not raw_path.startswith("/"):
            continue
        tail = src[m.end(): m.end() + 300]
        vm = re.search(r"method:\s*[\"'](\w+)[\"']", tail.split(")")[0] if ")" in tail else tail)
        path = re.sub(r"\$\{[^}]*\}", "{param}", raw_path)
        path = re.sub(r"(?<!/)\$\{[^}]*\}", "", path).split("?")[0]
        v = (vm.group(1) if vm else "GET").upper()
        line = src[: m.start()].count("\n") + 1
        out.append(Endpoint(v, "/" + path.lstrip("/"), "fetch-call",
                            file, line, "consumer", "TS-REQUEST-TEMPLATE"))
    # const ENDPOINT = '/api/x' constant + fetch(ENDPOINT) / request(ENDPOINT)
    consts = {}
    for m in re.finditer(
        r"const\s+(\w+ENDPOINT\w*|\w+API_PATH\w*)\s*=\s*[\"']([^\"']+)[\"']", src):
        consts[m.group(1)] = m.group(2)
    for m in re.finditer(
        r"(?:fetch|request)(?:<[^>]*>)?\(\s*(\w+ENDPOINT\w*|\w+API_PATH\w*)\b", src):
        if m.group(1) in consts:
            raw_path = consts[m.group(1)]
            if not raw_path.startswith("/"):
                continue
            tail = src[m.end(): m.end() + 300]
            vm = re.search(r"method:\s*[\"'](\w+)[\"']", tail.split(")")[0] if ")" in tail else tail)
            v = (vm.group(1) if vm else "GET").upper()
            line = src[: m.start()].count("\n") + 1
            out.append(Endpoint(v, raw_path, "endpoint-const",
                                file, line, "consumer", "TS-REQUEST-TEMPLATE"))
    return out


# ---------------------------------------------------------------- PATH-NORM
def path_norm(a: str, b: str) -> bool:
    """Equivalence under /api prefix delta + placeholder unification.
    Koa :name, TS ${expr} and REST {name} params all collapse to {param}."""
    def norm(s):
        s = s.strip()
        if not s.startswith("/"):
            s = "/" + s
        s = re.sub(r"\{webhook_?id\}", "{id}", s, flags=re.I)
        s = re.sub(r":(\w+)(?=/|$)", "{param}", s)      # koa :id → {param}
        s = re.sub(r"\{param\}|\{\w+\}", "{param}", s)  # unify all named params
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
