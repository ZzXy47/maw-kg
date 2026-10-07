# MAW-KG

Multi-Agent Workspace Knowledge Graph —— a code-understanding MCP server for
multi-repo, cross-platform projects. It bridges the CodeGraph indexer (symbol
index + call graphs) with an explicit cross-repo contract layer, so an agent
can ask "who calls this endpoint, across repos?" and get answers bound to
real symbols — never synthesized.

Built and validated against a real multi-platform codebase (Home Assistant
core / Android / iOS + a HarmonyOS ArkTS client + AAOS car codelabs).

[**English**](#english) | [**简体中文**](#简体中文) | [**日本語**](#日本語) | [**한국어**](#한국어)

---
## English

### Your AI agent finally understands your whole codebase — not just one repo at a time

You maintain a **multi-platform project**: a Python backend, an Android app, an
iOS client, maybe a HarmonyOS variant. Every AI coding assistant you've tried
suffers from the same wall — it can read *one* repo at a time, and it
**hallucinates cross-repo relationships** because it has no way to know that
the Kotlin `registerDevice()` call on line 45 hits the Python
`/api/mobile_app/register` route on line 123 of another repository.

**MAW-KG ends that.** It is an MCP server that gives any agent — Claude,
Hermes, or anything that speaks MCP — three connected abilities:

1. **Symbol-level understanding per repo** — search, source, call graphs,
   blast radius: "who calls this? what breaks if I change it?"
2. **Cross-repo contracts** — you declare once that
   `mobile_app.register ↔ registerDevice`, and every binding is verified
   against the real indexed symbols. If a refactor breaks the contract, it
   fails loudly. **No fabricated edges, ever** — if a binding can't be proven,
   you get an error, not a guess.
3. **Change fan-out** — `git diff` in the backend shows you exactly which
   mobile clients you just broke. Across repositories. In one query.

### Why you can trust the answers

Every other "AI code understanding" tool answers with heuristics. MAW-KG
answers with **verified bindings**: a contract endpoint only passes when the
symbol exists at the declared file and line in the CodeGraph index — exact
match, tolerance for small line drift, zero synthesis. The same discipline
covers path normalization (`/api/mobile_app/register` in the backend is the
same route as `{base}/mobile_app/register` in the app), generated-file
exclusion, and a hard rule: **a missing index or unresolved symbol is an
ERROR, never silently skipped.**

### Highlights

- **10 MCP tools** — explore / query / node / impact / contracts / cognition search / detect-changes / cross-impact / contract-check / status
- **9 route-extraction forms** across Python / Kotlin / Swift / TypeScript / ArkTS — 525 routes auto-matched at 78.7% on a real 679-file TypeScript monorepo, zero dead routes
- **Battle-tested governance** — writer liveness probes, stale-lock cleanup, session-end daemon recycling, transient-error retry, empty-shell index detection (a truncated index is *reported*, not trusted)
- **Windows-hardened** — GBK console corruption, host-filtered PATH, SYSTEMROOT-dependent node crashes: all fixed in production use
- **Bakeoff-validated** — 12/12 against GitNexus / CodeGraph / AOCI on real questions (report in `tests/bakeoff/`)

### Quick start

```bash
npm install -g @colbymchenry/codegraph   # the indexer kernel
pip install pyyaml
cp repos.yaml.example repos.yaml          # register your repos
cd /path/to/repo && codegraph init -v     # index each repo
python src/mcp_server.py serve            # stdio MCP server
```

Then point any MCP host at it. Full details in [Install](#install).

### Reporting problems

Errors are captured **locally** in `work/errors.jsonl` (values never logged —
only argument shapes; nothing leaves your machine). When something misbehaves:

```bash
python src/report.py          # writes work/report.md — review every line first
python src/report.py --issue  # files a GitHub issue with the report (or prints a prefilled URL)
```

No telemetry, no silent uploads, no auto-email.

---

## 简体中文

### 让你的 AI Agent 第一次真正「读懂」整个多端项目——而不是一次一个仓库

你维护着一个**多端项目**：Python 后端、Android 应用、iOS 客户端，可能还有鸿蒙变体。
你试过的每一个 AI 编程助手都撞在同一堵墙上——它一次只能读**一个**仓库，而跨仓库的
调用关系全靠**幻觉**：它没办法知道 Kotlin 第 45 行的 `registerDevice()` 打的是另一个
仓库里 Python 第 123 行的 `/api/mobile_app/register`。

**MAW-KG 终结这件事。** 它是一个 MCP 服务器，给任何会讲 MCP 的 agent
（Claude、Hermes……）三个连在一起的能力：

1. **仓库内符号级理解**——检索、源码、调用图、爆炸半径：「谁调用了它？改了它会炸到谁？」
2. **跨仓库契约**——你只需声明一次 `mobile_app.register ↔ registerDevice`，之后每个绑定
   都对着真实索引符号核验。重构破坏了契约就**大声报错**。**永远不伪造边**——绑定证明不了，
   你得到的是错误，不是猜测。
3. **变更扇出**——后端一个 `git diff`，立刻看到你刚刚炸到了哪些移动端。跨仓库，一条查询。

### 为什么答案可以信

其他「AI 代码理解」工具用启发式回答；MAW-KG 用**核验过的绑定**回答：契约端点只有
在符号真实存在于声明的文件与行号时才通过——精确匹配、容忍小幅行漂移、零合成。同样的
纪律覆盖路径归一化（后端的 `/api/mobile_app/register` 和 App 里的
`{base}/mobile_app/register` 是同一条路由）、生成文件排除，以及一条铁律：
**索引缺失或符号无法解析是 ERROR，绝不被静默跳过。**

### 亮点

- **10 个 MCP 工具**——探索 / 查询 / 符号节点 / 影响面 / 契约 / 认知检索 / 变更检测 / 跨仓影响 / 契约核验 / 状态
- **9 种路由抽取形态**，覆盖 Python / Kotlin / Swift / TypeScript / ArkTS——在真实 679 文件 TypeScript 单仓上 525 条路由自动匹配 78.7%，零死路由
- **生产级治理**——写入者存活探针、陈旧锁清理、会话结束守护进程回收、瞬态错误重试、空壳索引检测（被截断的索引会被**报告**，而不是被信任）
- **Windows 淬炼**——GBK 控制台乱码、宿主过滤 PATH、SYSTEMROOT 依赖崩溃：全部在生产中修掉
- **同题实测**——与 GitNexus / CodeGraph / AOCI 三方对标 12/12（报告在 `tests/bakeoff/`）

### 快速开始

```bash
npm install -g @colbymchenry/codegraph   # 索引内核
pip install pyyaml
cp repos.yaml.example repos.yaml          # 注册你的仓库
cd /path/to/repo && codegraph init -v     # 给每个仓库建索引
python src/mcp_server.py serve            # stdio MCP 服务器
```

任何 MCP 宿主接上即用。完整步骤见 [Install](#install)。

### 问题反馈

错误只会在**本地** `work/errors.jsonl` 里捕获（只记参数形态，不记值；
不会有任何数据离开你的机器）。出问题时：

```bash
python src/report.py          # 生成 work/report.md —— 请先逐行过目
python src/report.py --issue  # 附着报告提 GitHub issue（未登录 gh 时打印预填 URL）
```

没有遥测、没有静默上传、没有自动发邮件。

---

## 日本語

### AIエージェントが、初めてプロジェクト「全体」を理解する——一度に一つのリポジトリではなく

あなたは**マルチプラットフォームプロジェクト**を保守している：Pythonバックエンド、
Androidアプリ、iOSクライアント、さらにHarmonyOS版もあるかもしれない。試してきた
どのAIコーディングアシスタントも同じ壁にぶつかる——**一度に一つの**リポジトリしか
読めず、リポジトリを跨ぐ呼び出し関係は**ハルシネーション**でしかない。Kotlinの
45行目の `registerDevice()` が、別リポジトリのPython 123行目の
`/api/mobile_app/register` を叩いていることなど、知る術がない。

**MAW-KGがこれを終わらせる。** MCP対応のエージェント（Claude、Hermes等）に、
3つの連携した能力を与えるMCPサーバーだ：

1. **リポジトリ内のシンボルレベル理解**——検索・ソース・コールグラフ・影響範囲：「誰がこれを呼んでいる？変更したら何が壊れる？」
2. **リポジトリ横断契約**——`mobile_app.register ↔ registerDevice` を一度宣言すれば、全バインディングが実際のインデックス済みシンボルに対して検証される。リファクタで契約が壊れれば**大声でエラー**。**偽のエッジは絶対に作らない**——証明できないバインディングは、推測ではなくエラーとして返す。
3. **変更の波及**——バックエンドの `git diff` 一つで、今壊したモバイルクライアントがすぐ分かる。リポジトリ横断、1クエリで。

### なぜ答えを信頼できるのか

他の「AIコード理解」ツールはヒューリスティクスで答える。MAW-KGは**検証済みバインディング**で答える：契約エンドポイントは、シンボルが宣言されたファイルと行に実在する場合のみ通過——完全一致、わずかな行ドリフトは許容、合成はゼロ。同じ規律がパス正規化（バックエンドの `/api/mobile_app/register` とアプリの `{base}/mobile_app/register` は同じルート）、生成ファイル除外、そして鉄則：**インデックス欠落やシンボル未解決はERROR。静かにスキップされない。**

### ハイライト

- **10個のMCPツール**——探索 / 検索 / シンボルノード / 影響範囲 / 契約 / 認知検索 / 変更検出 / 横断影響 / 契約検証 / ステータス
- **9種のルート抽出形式**——Python / Kotlin / Swift / TypeScript / ArkTS対応。実際の679ファイルTypeScriptモノリポで525ルートを78.7%自動マッチ、デッドルートゼロ
- **実運用グレードのガバナンス**——書き込み者の生存プローブ、古いロックの清掃、セッション終了時のデーモン回収、一時エラーのリトライ、空インデックス検出
- **Windowsで鍛えられた**——GBKコンソール破損、PATHフィルタ、SYSTEMROOT依存のクラッシュ：すべて実運用で修正済み
- **同題ベンチマーク**——GitNexus / CodeGraph / AOCI との比較で12/12（レポートは `tests/bakeoff/`）

### クイックスタート

```bash
npm install -g @colbymchenry/codegraph   # インデックスカーネル
pip install pyyaml
cp repos.yaml.example repos.yaml          # リポジトリを登録
cd /path/to/repo && codegraph init -v     # 各リポジトリをインデックス
python src/mcp_server.py serve            # stdio MCPサーバー
```

MCP対応ホストなら何にでも接続できる。詳細は [Install](#install)。

### 問題の報告

エラーは**ローカルの** `work/errors.jsonl` にのみ記録される（値ではなく引数の
形のみ。あなたのマシンからデータが出ることはない）。問題が起きたら：

```bash
python src/report.py          # work/report.md を生成 — まず全行を確認
python src/report.py --issue  # レポートを添えてGitHub issueを作成（gh未認証ならURLを出力）
```

テレメトリなし、サイレント・アップロードなし、自動メールなし。

---

## 한국어

### AI 에이전트가 처음으로 프로젝트 "전체"를 이해합니다 — 한 번에 하나의 저장소가 아니라

**멀티 플랫폼 프로젝트**를 유지 관리하고 계시죠: Python 백엔드, Android 앱, iOS
클라이언트, 어쩌면 HarmonyOS 변형까지. 지금까지 시도한 모든 AI 코딩 어시스턴트는
같은 벽에 부딪힙니다 — **한 번에 하나의** 저장소만 읽을 수 있고, 저장소를 가로지르는
호출 관계는 **환각**일 뿐입니다. Kotlin 45번째 줄의 `registerDevice()`가 다른
저장소의 Python 123번째 줄 `/api/mobile_app/register`를 호출한다는 사실을 알 방법이
없습니다.

**MAW-KG가 이것을 끝냅니다.** MCP를 말하는 모든 에이전트(Claude, Hermes 등)에게
연결된 세 가지 능력을 부여하는 MCP 서버입니다:

1. **저장소 내 심볼 수준 이해** — 검색, 소스, 콜 그래프, 영향 반경: "누가 이것을 호출하나? 변경하면 무엇이 깨지나?"
2. **저장소 간 계약** — `mobile_app.register ↔ registerDevice`를 한 번만 선언하면, 모든 바인딩이 실제 인덱싱된 심볼에 대해 검증됩니다. 리팩토링이 계약을 깨뜨리면 **크게 에러**가 납니다. **가짜 엣지는 절대 만들지 않습니다** — 증명할 수 없는 바인딩은 추측이 아니라 에러로 돌아옵니다.
3. **변경 전파** — 백엔드의 `git diff` 하나로 방금 깨뜨린 모바일 클라이언트를 즉시 확인합니다. 저장소를 가로질러, 한 번의 쿼리로.

### 왜 답을 신뢰할 수 있는가

다른 "AI 코드 이해" 도구들은 휴리스틱으로 답합니다. MAW-KG는 **검증된 바인딩**으로 답합니다: 계약 엔드포인트는 심볼이 선언된 파일과 줄에 실제로 존재할 때만 통과됩니다 — 정확한 매칭, 작은 줄 드리프트는 허용, 합성은 제로. 같은 규율이 경로 정규화(백엔드의 `/api/mobile_app/register`와 앱의 `{base}/mobile_app/register`는 같은 라우트), 생성 파일 제외, 그리고 철칙을 덮습니다: **인덱스 누락이나 심볼 미해결은 ERROR입니다. 조용히 건너뛰지 않습니다.**

### 하이라이트

- **10개의 MCP 도구** — 탐색 / 검색 / 심볼 노드 / 영향 반경 / 계약 / 인지 검색 / 변경 감지 / 교차 영향 / 계약 검증 / 상태
- **9가지 라우트 추출 형식** — Python / Kotlin / Swift / TypeScript / ArkTS 지원. 실제 679파일 TypeScript 모노레포에서 525개 라우트 78.7% 자동 매칭, 데드 라우트 0
- **실전급 거버넌스** — 라이터 생존 프로브, 오래된 락 정리, 세션 종료 데몬 회수, 일시적 에러 재시도, 빈 인덱스 감지
- **Windows에서 단련됨** — GBK 콘솔 깨짐, PATH 필터링, SYSTEMROOT 의존 크래시: 모두 실전에서 수정 완료
- **동일 문제 벤치마크** — GitNexus / CodeGraph / AOCI와의 비교에서 12/12 (보고서는 `tests/bakeoff/`)

### 빠른 시작

```bash
npm install -g @colbymchenry/codegraph   # 인덱서 커널
pip install pyyaml
cp repos.yaml.example repos.yaml          # 저장소 등록
cd /path/to/repo && codegraph init -v     # 각 저장소 인덱싱
python src/mcp_server.py serve            # stdio MCP 서버
```

MCP 호스트라면 무엇에든 연결됩니다. 자세한 내용은 [Install](#install)을 보세요.

### 문제 보고

오류는 **로컬** `work/errors.jsonl`에만 기록됩니다(값이 아니라 인자 형태만.
사용자의 머신에서 데이터가 나가는 일은 없습니다). 문제가 생기면:

```bash
python src/report.py          # work/report.md 생성 — 먼저 모든 줄을 검토하세요
python src/report.py --issue  # 보고서를 첨부해 GitHub issue 생성(gh 미인증 시 URL 출력)
```

텔레메트리 없음, 자동 업로드 없음, 자동 이메일 없음.

---

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
