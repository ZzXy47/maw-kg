# MAW-KG

Multi-Agent Workspace Knowledge Graph —— 面向多端全栈大项目的仓库理解插件。

设计稿：`E:/CrossDevice_Agent_GitNexus_Pilot/_audit/MAW-KG-design-v3.md`（v3.1）
全部实测底稿：`E:/CrossDevice_Agent_GitNexus_Pilot/_audit/`

## 目录

```
D:/maw-kg/
  contracts/contracts.yaml   # 跨端契约清单（git 版本化，人审）
  docs/contracts-schema.md   # 契约模式设计
  src/contract_check.py      # 核对脚本（P0 交付）
  tests/p0_green_bridge.py   # P0 绿灯验收（对照红灯脚本六断言）
```

## P0 用法

```bash
# 全量核对（任一绑定失败即退出非零——宁可报错不给假边）
python src/contract_check.py

# JSON 输出
python src/contract_check.py --json

# 变更影响：改了后端哪些契约受波及
python src/contract_check.py --check-diff ha-core HEAD

# P0 验收（四项全绿）
python tests/p0_green_bridge.py
```

## 依赖

- Python 3.14+（已用 Hermes 自带解释器验证）
- PyYAML（已装 6.0.3）
- 夹具仓的 CodeGraph 索引（`E:/CrossDevice_Agent_GitNexus_Pilot/repos/*/.codegraph/`，已建）

## 状态

- **P0 完成（2026-10-06）**：3 条真实跨端契约（设备注册 / Watch 注册 / webhook 更新），14 项绑定核对全过；diff 影响报告正反例验证通过；绿灯桥四项全绿。
- P1（CodeGraph 内核 + MCP 常驻 + 守护进程治理）待开工。

## Status

- P0 contract schema + checker: 3 contracts, 14 bindings, 14 pass / 0 fail (2026-10-06)
- P1 MCP server: 8 tools, G0 governance, env selfcheck — 15/15 + git acceptance 4/4
- P2 cross-repo sync + detect-changes local subgraph: 8/8 real bindings, 0.01s
- P3 extractors: NINE forms (PY-CLASS-ROUTE / KT-URL-BUILDER / KT-RETROFIT-URL / SW-REQUEST-WRAPPER / SW-ARRAY-PATH / PATH-NORM / TS-KOA-ROUTE / TS-REQUEST-TEMPLATE / ARKTS-OHOS-HTTP) — 9/9 + redlight 6/6
- P4 L4 cognition + drift: 5/5
- ekko-studio fixture: 525 routes, 413 auto-matched (78.7%), zero dead routes
- Fix round 2026-10-06 (403c1b1): daemon-leak tree-kill (verified CLEAN), maw_cross_impact diff mode, env selfcheck read-only tolerance, ArkTS form 9
- Full regression: 6 suites green

Known open: 19 client-string route pairs unextractable by regex (tree-sitter is the P5 path); ekko Android shell repo not in this repo (APK build unverified).
