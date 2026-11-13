# 12 · 补丁说明与配置指南：已决岗位不再回池

> 对应 2026-11-13 的前端补丁。本文回答五件事：**改了什么、要不要改配置、怎么应用、怎么验证、怎么回滚。**
> 事故来龙去脉与判定规则细节见 [11-guardrails.md](11-guardrails.md) 第 16 条。

---

## 0. 一句话结论

这个补丁只在**渲染前加一层过滤**，不改表结构、不改查重规则、不需要新增任何服务端组件。

需要你动手的配置只有两类：

| 场景 | 要不要改 |
|---|---|
| 只是升级（沿用现有城市） | **不用改任何配置**，替换 `app/index.html` 后重新发布即可 |
| 你投的城市不在默认列表里 | 改 `CITY_TAIL` 一行 |
| 想独立跑审计脚本 `audit-decisions.py` | 配 2–3 个环境变量（见第 3.3 节） |

---

## 1. 它解决什么问题

**症状**：岗位已经点过「不投」或「授权投递」，下一轮采集之后又出现在岗位池里。

**根因不是一处，是三条叠加**：

1. **标题噪音让查重键撞不上**。同一岗位在不同平台/批次的写法：
   `FP&A Supervisor` / `FP&A Supervisor (MJ003311)` / `FP&A Supervisor（上海）`。
   归一化会把括号剥掉，但括号里的 `MJ003311`、`上海` 留在了键里，于是被当成新岗位。
2. **岗位池只认状态，不认你的历史决定**。`loadPool()` 原来只筛 `status === '待确认'`，
   从不拿待确认记录去比对你已决的岗位，副本自然照常显示。
3. **采集只有 INSERT，没有"回头看你决定过什么"**。跨批次漏判时，数据库里就真的多了一条新行。

**为什么选择"隐藏"而不是"删除"**：状态是你的资产。补丁只做「不显示」，不删行、不改状态。
你点「↩ 移回待确认」，它立刻回到池子，不会出现"想撤销却发现数据被删了"的情况。

---

## 2. 改动清单

| 文件 | 类型 | 改动内容 | 配置影响 |
|---|---|---|---|
| `app/index.html` | 前端（仓库脱敏版） | 新增 `CITY_TAIL` / `looseKey()` / `decidedIndex()` / `urlKeyOf()`；岗位池与待确认列表渲染前过滤 | 需填你自己的 3 行连接配置（仓库里是占位符） |
| `job-agent/index.html` | 前端（线上运行版，含真实凭据） | 同上 | 无 |
| `scripts/test-decisions.js` | 测试（新增） | 9 个场景，从 HTML 抽取真实函数执行 | 无 |
| `scripts/audit-decisions.py` | 审计（新增） | 只读扫描全库，报告「待确认里是否还有已决岗位副本」 | **有**，见 3.3 |
| `scripts/db_conn.py` | 连接层（新增） | 统一取数：标准 PostgreSQL 或 WorkBuddy 云库 MCP | **有**，见 3.3 |
| `.github/workflows/ci.yml` | CI | 增加 `test-decisions.js` 与 `audit-decisions.py --self-test` | 无 |
| `docs/11-guardrails.md` | 文档 | 事故台账第 16 条 + 收尾自检第 7 项 | 无 |

**没有改动的部分**（重要，避免误解）：

- 采集侧的全状态永久查重逻辑 —— 一字未动（这是红线，见 [11-guardrails.md](11-guardrails.md) 第四节）
- 数据库表结构 —— 不加字段、不建索引、不建表
- 状态机与状态名 —— 不新增状态
- `endpoint` / `publishableKey` / `oauthRelayBaseUrl` —— 补丁不碰网络层

---

## 3. 配置说明

### 3.1 不需要改的（升级用户直接跳过）

如果你只是把 `app/index.html` 换成新版本、沿用原来的云库和账号，那么**一项配置都不用动**。
补丁没有引入新的网络请求、新的表、新的权限要求。

### 3.2 唯一建议按城市调整：`CITY_TAIL`

在 `app/index.html` 里搜索 `CITY_TAIL`（约第 670 行，前面有 `⚙️ 可配置项` 注释）。

```js
const CITY_TAIL = /(上海|北京|深圳|广州|杭州|苏州|南京|成都|武汉|西安|天津|重庆|中国|china|shanghai|beijing|shenzhen|guangzhou|hangzhou|suzhou|nanjing|chengdu|wuhan)$/;
```

**它干什么**：宽松键会把岗位标题**末尾**的这些城市名（中文或拼音）剥掉，再和你的已决岗位比对。
「`FP&A Manager`」和「`FP&A Manager（上海）`」因此能认出是同一岗位。

**什么时候要改**：你投的城市不在表里。例如主要投深圳、香港、新加坡：

```js
const CITY_TAIL = /(上海|北京|深圳|广州|香港|新加坡|...|hongkong|singapore)$/;
```

**改错的后果**：
- 漏写某城市 → 带该城市后缀的副本可能漏进池子（**只是漏拦**，不会误删、不会改状态）
- 写得过宽（把公司名、通用词写进去）→ 可能把不同岗位误判为同一个，导致正常岗位被隐藏（可撤销，点「↩ 移回待确认」即可回来）

**纪律**：只写"地名"，不要写公司名；改完必须跑

```bash
node scripts/test-decisions.js app/index.html
```

### 3.3 独立运行 `audit-decisions.py` 需要的配置

审计脚本是**只读**的，只执行 `SELECT`。它原来依赖开发机上的临时模块，现已改为两种可配置后端，按优先级自动选择。

| 变量 | 必填 | 示例 | 说明 |
|---|---|---|---|
| `DATABASE_URL` | 二选一 | `postgresql://user:pass@host:5432/postgres` | 标准 PostgreSQL。用只读账号即可。需 `pip install psycopg2-binary` |
| `WB_MCP_CONFIG` | 二选一 | 含 `url` / `headers` 的 mcpServers JSON | WorkBuddy 云库 MCP 通道 |
| `WB_APP_ID` | 用 MCP 时必填 | `wbapp_xxxxxxxx` | 你的 applicationId |
| `OWNER_ID` | **必填** | `wb:xxxxxxxx` | 数据的归属标识，也可用 `--owner` 传入 |
| `PENDING_STATUS` | 可选 | `待确认` | 默认「待确认」，状态名不同才需要改 |

**取 `OWNER_ID` 的方法**（在云库控制台或任意能跑 SQL 的地方）：

```sql
SELECT DISTINCT owner_id FROM jobs LIMIT 5;
```

**完整示例（PostgreSQL）**：

```bash
export DATABASE_URL='postgresql://readonly:pass@db.example.com:5432/postgres'
export OWNER_ID='wb:xxxxxxxx'
python scripts/audit-decisions.py
```

**完整示例（WorkBuddy 云库）**：

```bash
export WB_MCP_CONFIG='{"mcpServers":{"genie-baas":{"url":"…","headers":{…}}}}'
export WB_APP_ID='wbapp_xxxxxxxx'
export OWNER_ID='wb:xxxxxxxx'
python scripts/audit-decisions.py
```

两个后端都没配时，脚本会直接打印上面这段配置示例并返回退出码 `2`，不会抛 `ModuleNotFoundError`。

**不连库也能验证规则本身**：

```bash
python scripts/audit-decisions.py --self-test    # 7 个负向用例，退出码 0 才算通过
```

### 3.4 如果你的状态名不一样

判定逻辑用的是一个简单语义：**「不是待确认」= 已决**。

如果你把新采集的岗位叫「新岗位」而不是「待确认」，必须同时改三处，漏一处会出现「岗位池全空」：

| 位置 | 改什么 |
|---|---|
| 前端 `loadPool()` | `j.status === '待确认'` → 你的状态名 |
| 前端 `decidedIndex()` | `j.status !== '待确认'` → 你的状态名 |
| 审计脚本 | `export PENDING_STATUS='新岗位'` |

---

## 4. 三种应用方式

### A. 通过 git 使用（推荐）

```bash
git pull
```

然后按 3.1 / 3.2 决定要不要改 `CITY_TAIL`，再重新发布静态站点。

### B. 已有线上部署，只想更新前端

1. 用新版 `job-agent/index.html` 整体替换（注意保留你自己的 `publicConfig` 三行）。
2. 只做增量的话，对照第 2 节表格，把 `CITY_TAIL` / `urlKeyOf` / `looseKey` / `decidedIndex` 四段和两处过滤加进去。
3. **重新发布静态站点** —— 这一步不能省。GitHub 上 push 完了不等于线上已更新，
   打开线上链接看到的仍是旧文件。

### C. 只想用审计能力，不换前端

拷两个文件即可，不需要动 `index.html`：

```bash
scripts/db_conn.py
scripts/audit-decisions.py
```

按 3.3 配好环境变量后直接运行。适合已经手工清理过数据、只想定期体检的场景。

---

## 5. 验证清单

| 目的 | 命令 | 期望 |
|---|---|---|
| 判定规则没写错 | `node scripts/test-decisions.js app/index.html` | `通过 9 / 9` |
| 审计规则没写错 | `python scripts/audit-decisions.py --self-test` | `自检通过 7 / 7`，退出码 0 |
| 线上库有没有回流 | `python scripts/audit-decisions.py` | 退出码 0，输出「没有已决岗位回流」 |
| 前端脚本能否执行 | `node scripts/smoke-frontend.js app/index.html` | 两份都通过 |
| 文档没断链 | `python scripts/check-docs-links.py` | 全部可达 |

**手工验收**（最有说服力）：把一条已标「不合适」的岗位，用同名但带 `(MJ编号)` 的新卡片重采一遍。
岗位池计数应出现「已隐藏 1 条与你已有决定重复」，同时该岗位仍留在「不投」清单里。

---

## 6. 回滚

补丁不产生任何脏数据，回滚很干净：

- **前端**：`git revert` 或换回旧版 `index.html`，重新发布。被隐藏的副本会重新显示（数据一直都在）。
- **脚本**：删掉 `scripts/db_conn.py`、`scripts/audit-decisions.py`、`scripts/test-decisions.js`，
  并同步删掉 `.github/workflows/ci.yml` 里引用它们的两步，否则 CI 会因找不到文件而红。

不需要清理数据库、不需要修状态、不需要重建表。

---

## 7. 这套机制的边界（诚实说明）

- **不做模糊匹配到"不同岗位"的程度**。宽松键只动两处噪音：`(MJ编号)` 这类编号、标题末尾的城市。
  宁可漏拦一条，也不误伤一批。
- **不替代采集前查重**。这层过滤是最后一道兜底，不是第一道。第一道仍然是入库前的全状态永久查重。
- **不解决跨账号问题**。所有判定都限定在单个 `owner_id` 内，多人共用一个部署时互不可见。
- **隐藏不等于清理**。若某岗位确实已在别处投过、库里的副本永远不该存在，需要人工判断后清理——脚本不会自动删。
