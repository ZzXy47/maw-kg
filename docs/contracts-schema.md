# MAW-KG 契约模式 v1（contracts.yaml）

## 设计

P0 的数据模型：跨端契约显式登记，受 git 版本控制。一条契约 = 一个跨端接口/事件/数据结构的**两端符号绑定** + 变更核对规则。

### contracts.yaml 结构

```yaml
version: 1
contracts:
  - id: mobile-app-registration          # 唯一 ID（kebab-case）
    kind: http                            # http | event | schema | topic
    description: mobile_app 设备注册接口
    provider:                             # 契约的"服务端"
      repo: ha-core                       # registry 中的仓别名
      symbol: RegistrationsView.post      # 符号限定名（或文件路径锚）
      file: homeassistant/components/mobile_app/http_api.py
      line: 67
    consumers:                            # 契约的"消费端"（1..N）
      - repo: ha-android
        symbol: IntegrationRepositoryImpl.registerDevice
        file: common/src/main/kotlin/io/homeassistant/companion/android/common/data/integration/impl/IntegrationRepositoryImpl.kt
        line: 121
        path_variant: /api/mobile_app/registrations   # 实际请求路径（供归一化对照）
      - repo: ha-ios
        symbol: HAAPI.register
        file: Sources/Shared/API/HAAPI.swift
        line: 564
        path_variant: /mobile_app/registrations       # 无 /api 前缀——PATH-NORM 用例
    checks:                               # 核对脚本按此核对
      - path_match: normalized            # 两端路径经归一化后必须一致
      - symbol_exists: true               # 所有 symbol 必须能在索引中精确找到
    meta:
      owner: Z哥
      created: 2026-10-06
```

### 核对脚本职责（maw_contract_check 的 CLI 前身）

1. 加载 contracts.yaml + 各仓 CodeGraph 索引（.codegraph/codegraph.db）
2. 对每条契约：
   - provider/consumer 的 file:line 处符号必须存在且 qualified_name 匹配（精确，不模糊）
   - path_variant 归一化（去 base 前缀差异）后两端一致
   - generated/errors 文件排除（读 files 表）
3. 输出：per-contract PASS/FAIL 明细 + 退出码（任一 FAIL 即非零——"失败即报"原则）
4. `--check-diff <ref>` 模式：对 git diff 涉及的文件，报告波及哪些契约

### 红灯脚本关系

`repro_endpoint_extraction.py` 的六断言在 P0 后转绿：
- route-node×3、auto-contracts、real-bound-contracts → 由契约核对脚本产出"已绑定真实符号"的事实（写 endpoint-extraction-green.json）
- cross-impact → contract_check --check-diff 在 core 仓 http_api.py 有 diff 时报出 mobile-app-registration 契约受影响
