# MAW-KG

Multi-Agent Workspace Knowledge Graph —— a code-understanding MCP server for
multi-repo, cross-platform projects. It bridges the CodeGraph indexer (symbol
index + call graphs) with an explicit cross-repo contract layer, so an agent
can ask "who calls this endpoint, across repos?" and get answers bound to
real symbols — never synthesized.

Built and validated against a real multi-platform codebase (Home Assistant
core / Android / iOS + a HarmonyOS ArkTS client + AAOS car codelabs).

## What it does

- **10 MCP tools** (stdio JSON-RPC): `maw_explore` / `maw_query` / `maw_node` /
  `maw_impact` / `maw_contracts` / `maw_cognition_search` /
  `maw_detect_changes` / `maw_cross_impact` / `maw_contract_check` / `maw_status`
- **Symbol search + blast radius** per repo (CodeGraph-backed, budget-capped)
- **Cross-repo contracts**: YAML-declared provider/consumer bindings, exact-match
  verified against each repo's index — a broken binding fails loudly
- **Change fan-out**: `git diff` → changed symbols → affected contracts
- **L4 cognition layer**: tagged FRAS entries over contracts (keyword/tag search)

Core principles: explicit contracts; bind to real symbols; exact match only;
path normalization up front; generated files excluded; no fabricated edges
("宁可报错不给假边" — fail loudly, never invent an edge).

## Install

Requirements:

- Python 3.10+ (developed on 3.14)
- Node.js 18+ on PATH
- git on PATH
- The [CodeGraph](https://www.npmjs.com/package/@colbymchenry/codegraph) CLI:
  ```bash
  npm install -g @colbymchenry/codegraph   # or into a local node_modules
  ```
- PyYAML: `pip install pyyaml`

Setup:

1. Clone this repo.
2. Register your repos:
   ```bash
   cp repos.yaml.example repos.yaml
   # edit repos.yaml — absolute paths, one per line under repos:
   ```
3. Build an index for each registered repo (inside that repo's directory):
   ```bash
   cd /path/to/your/repo && codegraph init -v
   ```
   Use `init -v`, not `index`: piped/quiet output can truncate silently and
   leave an empty-shell index (`maw_status` flags those as `suspect-empty`).
4. Optional env overrides (win over repos.yaml / PATH):
   - `MAW_KG_NODE_EXE` — absolute path to node
   - `MAW_KG_CG_SHIM` — absolute path to the codegraph npm shim
   - `MAW_KG_GIT_EXE` — absolute path to git

Run the server:

```bash
python src/mcp_server.py serve
```

Register it with any MCP host (Claude Desktop, Hermes, etc.) as a stdio server.

## Quick verification

```bash
python src/mcp_server.py env          # cluster-size self-check
python src/contract_check.py          # verify all contract bindings
```

## Layout

```
contracts/contracts.yaml   # cross-repo contract registry (versioned, human-reviewed)
contracts/cognition.yaml   # L4 FRAS entries (tagged contract cognition)
docs/contracts-schema.md   # contract schema design
src/mcp_server.py          # MCP stdio server + daemon governance
src/kg_config.py           # single-source config resolution (env > repos.yaml > PATH)
src/contract_check.py      # P0 binding checker
src/cross_sync.py          # P2 cross-repo sync + local subgraph impact
src/extractors.py          # P3 route extraction (nine forms)
src/detect_changes.py      # diff → symbols → contract fan-out
src/cognition.py           # L4 FRAS layer
repos.yaml.example         # repo registry template (copy to repos.yaml)
tests/                     # verification suites + bakeoff harnesses
```

## Contract example

```yaml
contracts:
  - id: mobile-app-register
    kind: http
    description: Mobile app registration endpoint
    provider: {repo: ha-core, symbol: mobile_app.register, file: "...", line: 123,
               path_variant: "/api/mobile_app/register"}
    consumers:
      - {repo: ha-android, symbol: registerDevice, file: "...", line: 45,
         path_variant: "/api/mobile_app/register"}
    checks: [symbol_exists, path_match]
```

P0 CLI usage (all scripts runnable standalone):

```bash
python src/contract_check.py                     # verify all bindings (non-zero on FAIL)
python src/contract_check.py --json              # JSON output
python src/contract_check.py --check-diff ha-core HEAD   # which contracts a diff touches
```

## Status

- P0 contract schema + checker — 14/14 bindings green
- P1 MCP server — 10 tools, G0 governance (writer liveness probe, stale-lock
  cleanup, session-end daemon recycling, transient-error retry), env selfcheck
- P2 cross-repo sync + detect-changes local subgraph — 8/8 real bindings
- P3 extractors — nine forms (PY-CLASS-ROUTE / KT-URL-BUILDER / KT-RETROFIT-URL /
  SW-REQUEST-WRAPPER / SW-ARRAY-PATH / PATH-NORM / TS-KOA-ROUTE /
  TS-REQUEST-TEMPLATE / ARKTS-OHOS-HTTP), 9/9 + redlight 6/6
- P4 L4 cognition + drift — 5/5
- ekko-studio fixture: 525 routes, 413 auto-matched (78.7%), zero dead routes
- Bakeoff vs GitNexus / CodeGraph / AOCI — 12/12 (report in `tests/bakeoff/`)
- O-round: prewarm (first explore 22.8s→4.9s), detect-changes with
  quiesce-sync-lock-retry, FRAS keyword search, orphan-daemon reap
- Windows hardened: UTF-8 stdio reconfigure (GBK console corruption),
  absolute GIT_EXE resolution (host-filtered PATH), SYSTEMROOT guarantee for
  node children, index-size health check (empty-shell detection)
- Release round 2026-10-07: MIT license; all user-absolute paths removed
  (single-source `kg_config.py`: env `MAW_KG_*` > `repos.yaml` > PATH);
  `repos.yaml` gitignored with `repos.yaml.example` template; REPO_ROOTS
  single-sourced across contract layer; README rewritten for external users;
  test JSON artifacts gitignored

Known open: 19 client-string route pairs unextractable by regex (tree-sitter
is the planned P5 path).

## License

MIT — see [LICENSE](LICENSE).
