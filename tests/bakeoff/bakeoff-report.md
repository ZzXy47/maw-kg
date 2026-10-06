# Bake-off 2026-10-06 · MAW-KG vs GitNexus vs CodeGraph vs AOCI

同一套 12 题验收（ground truth 人工核源码，见 ground_truth.md），四工具同题作答。
夹具矩阵：ekko-studio（TS 三端 0c28364）/ homogram-arkts（鸿蒙 fb9aaaa）/ aaos-car-codelabs（车机 8102fbf）/ HA core+android+ios 三仓。
工具版本：MAW-KG 627fa3f · GitNexus 1.6.12 · CodeGraph 1.6.2 · AOCI rc17。

## 总分矩阵

| 题 | 问题 | MAW-KG | GitNexus | CodeGraph | AOCI |
|---|---|---|---|---|---|
| Q1 | ekko 路由→处理器 | **PASS** | PARTIAL | PARTIAL | N/A-SCOPE |
| Q2 | ekko 客户端消费者 | **PASS** | **PASS** | **PASS** | N/A-SCOPE |
| Q3 | 跨包影响（server→client） | **PASS** | MISS | MISS | N/A-SCOPE |
| Q4 | HA 跨仓影响→三端 | **PASS** | MISS | MISS | PARTIAL |
| Q5 | ArkTS HTTP 枚举 | **PASS** | PARTIAL(1) | PARTIAL(2) | N/A-SCOPE |
| Q6 | 车机入口类定位 | **PASS** | **PASS** | **PASS** | N/A-SCOPE |
| Q7 | 新鲜度（秒） | **PASS 22.8s** | PASS 49s | **PASS 6.3s** | N/A-SCOPE |
| Q8 | 假阳性探针 | **PASS** | **PASS** | **PASS** | **PASS** |
| Q9 | worktree 隔离 | **PASS** | N/A(3) | **FAIL** | N/A-SCOPE |
| Q10 | 精确匹配纪律 | **PASS** | **PASS** | **PASS** | N/A-SCOPE |
| Q11 | 契约核对（零合成） | **PASS 14/14** | MISS(4) | MISS | PARTIAL(5) |
| Q12 | 守护治理（stale 自清） | **PASS** | N/A | **PASS** | N/A-SCOPE |
| **合计** | | **12/12** | **5/12** | **6/12** | **1/12**（范围受限） |

### 脚注
1. GitNexus 对 .ets 仅 File 节点零符号（此前 R5 已证）；本题 PARTIAL 是因 cypher 计数显示 1（探针行差异，实为零符号能力）。
2. CodeGraph 对 .ets 实际有符号（52 class/366 method/1507 总符号——**修正此前"File only"的记录，那是 GitNexus 的行为不是 CG 的**），但无 HTTP 端点语义，枚举不出 `/tg/notify`。
3. GitNexus 无常驻 daemon（CLI 每调用独立进程），worktree 未建索引，未测。
4. GitNexus group 面输出无 manifest:: 字样（本版输出格式变化），但跨仓 impact 命中 0（Q4 MISS），契约语义实际不可用。
5. AOCI 是认知标注层：search/report 可用，条目需先人工撰写（本工作区 15 条引用来自早前轮次），证据绑定门槛导致撰写成本高（[impact_resolution_failed] 已知）。

## 关键判读

**MAW-KG 12/12 全过**，包括三个对照组全灭的能力：
- **Q3/Q4 跨包跨仓影响**：契约层的独门——GitNexus 自动匹配 0、CodeGraph 单仓无跨仓、AOCI 无检索面。
- **Q5 ArkTS HTTP**：形态 9 抽取器的独门（CG 有符号但无端点语义；GitNexus 零符号）。
- **Q9 worktree 隔离**：CG 原生 query 是模糊段匹配（WT_B 查询返回 WT_A）——MAW 精确过滤层修的正是这个。
- **Q11 契约核对**：14 绑定全真实符号，对照组无一有此概念。

**对照组强项（MAW-KG 需要正视的）**：
1. **CodeGraph Q7 新鲜度 6.3s vs MAW 22.8s**：同用 CG 内核，MAW 慢在 MCP 会话层（daemon 冷启 + JSON-RPC 往返）。优化点①。
2. **GitNexus Q7 49s 但带语义**：detect-changes 直接给出「符号→file:line」映射（`Function gnFreshnessProbe → IntegrationRepositoryImpl.kt`），这个 diff→符号映射 MAW 没有对等命令。优化点②。
3. **AOCI Q4 PARTIAL**：认知条目可被 keyword 检索——MAW 的 L4 cognition.yaml 目前只做 drift 检测，**没有检索工具面**（maw_cognition_search 缺失）。优化点③。
4. **CodeGraph Q7 每次 CLI 冷启仅 0.4s**（Q12 里 query rc=0 0.4s）：MAW MCP 常驻会话的首查延迟可优化。

## 优化清单（按价值排序）

| # | 优化项 | 来源 | 预期收益 |
|---|---|---|---|
| O-1 | MCP 会话预热：mcp_server 启动时预初始化 CG daemon（而非首查冷启） | Q7 22.8s vs 6.3s | 首查延迟 ~4x |
| O-2 | `maw_detect_changes` 工具：git diff → 变更符号 + 契约关联（借 GitNexus 语义，CG sync 后 diff nodes 表） | GitNexus Q7 语义优势 | diff 即影响面，不用全量 impact |
| O-3 | `maw_cognition_search` 工具：FRAS 条目 keyword/tag 检索（AOCI 同款能力，落在自家 cognition.yaml 上） | AOCI Q4 | L4 认知层从"只写不读"变可检索 |
| O-4 | 抽取器 tree-sitter 化（P5）：19 条 client-string + .vue 模板深度解析 | ekko 78.7% 上限 | 匹配率 → 95%+ |
| O-5 | daemon 常驻复用跨 MCP 调用（当前每会话独立 daemon 冷启） | Q7/Q12 时序 | 全链路延迟稳定性 |

## 环境账（全部可复核）

- 夹具 6 仓测试后 tracked-dirty：仅 ha-core 2 项**测试前已存在**（AGENTS.md +104 行、http_api.py CRLF-only），本轮实验零新增污染；其余 5 仓 clean（?? .codegraph/.aoci 为索引目录，非源码改动）。
- harness 自身修了 4 个 bug：cypher `--params` 不存在（GitNexus CLI 无此参数）、detect-changes 参数形态、AOCI 调用式（`mcp --repo`）、Windows 子进程 env 必须 `{**os.environ}`（node 原生模块缺 SystemRoot 即 rc 134 崩溃——这个坑在三个 harness 里各踩了一次）。
- 结果 JSON：mawkg-results.json / codegraph-results.json / gitnexus-results.json / aoci-results.json。

## 结论

MAW-KG 在自家设计的验收维度全绿，且四个对照组的独门能力（CG 单仓符号/新鲜度、GitNexus diff 语义、AOCI 认知检索）各有值得吸收的下一层——这正是 O-1~O-5 优化清单的来源。**无一项需要推倒重来；架构方向被横向对比验证成立。**
