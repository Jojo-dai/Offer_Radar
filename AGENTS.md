# AGENTS.md — 复刻规格（机器可读）

本文件写给编码 Agent（Claude Code / Codex / Cursor / Devin 等）。目标：**仅凭本文件 + 仓库内容，从零复刻一个可运行的「投递助手」**，不需要读 README 的叙事部分。

阅读顺序：本文件 → `docs/04-database.md` → `docs/05-automations.md` → `app/index.html` → `scripts/*`。

---

## 0. 复刻完成判据（Definition of Done）

全部满足才算复刻成功：

- [ ] `scripts/schema.sql` 已在目标云数据库执行成功，4 张表存在且 RLS 已启用（策略名可见）
- [ ] `app/index.html` 可访问，未登录时显示登录按钮，登录后可看到 4 个步骤页签
- [ ] 上传一份 docx 简历 → 能解析出文本 → 生成画像 → 画像可确认（`profiles.confirmed = true`）
- [ ] 粘贴 `samples/demo-jobs.json` 到「智能导入」→ 提示导入 6 条、跳过重复 0 条
- [ ] 点「🧮 按画像批量打分」→ 6 条岗位出现 0-100 分数与 ≤30 字理由
- [ ] 3 个定时任务存在，时间分别为 08:00 / 18:00 / 每小时
- [ ] `bash scripts/check-network.sh` 两条硬断言全过；未过时领英段必须跳过而不是直连抓取
- [ ] 手动点「⚡ 通知 Agent 立即采集」→ `agent_tasks` 出现 1 条 `pending` 记录 → 下一小时检查点消费后变 `done` / `failed`（含原因）
- [ ] `docs/assets/architecture.svg` 与 `docs/assets/workflow.svg` 存在且被 README 引用（整体架构 + 七步工作流各一张）
- [ ] 非 WorkBuddy 通道复现时：越权自检返回 0 行（`set_config('app.uid','user-A')` 后读不到 `user-B` 的任何行）

---

## 1. 技术形态（不要过度设计）

| 项 | 约束 |
|---|---|
| 前端 | **单文件** `app/index.html`（内联 CSS + JS，无构建、无 npm） |
| 后端 | **无自建后端**。数据库 / LLM / 认证全部走 WorkBuddy Cloud SDK |
| SDK | `<script src="https://cdn.jsdelivr.net/npm/@tencent-ai/workbuddy-cloud-sdk@dev/lib/index.global.js"></script>`，全局对象 `cloud` |
| 数据库 | PostgreSQL（云托管），通过 `cloud.database.from('表名')` 访问 |
| LLM | `cloud.llm.chat.completions.create(...)`，免密钥；必须 `temperature: 0.3` + `response_format: { type: 'json_object' }` |
| 认证 | `cloud.auth.signInWithOAuth({ provider: 'workbuddy' })`，回调 `cloud.auth.handleWorkBuddyCallback()` |
| 定时 | 平台侧自动化任务（cron / RRULE），prompt 见 `docs/05-automations.md` |
| 采集 | 猎聘：无头浏览器 CLI 抓 DOM；领英：用户真实浏览器（扩展通道）读可见 DOM |

**硬性禁止**：引入 React/Vue/打包器、写 Node/Python 服务端、把 `applicationId` 写进前端、把平台账号密码存进库。

---

## 2. 数据契约（不可改名，前端与任务 prompt 都依赖）

### 2.1 `profiles`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | bigint PK | |
| `owner_id` | text | `auth.uid()`，全表隔离键 |
| `owner_name` | text | 展示用 |
| `target_profile` | jsonb | 见下方结构 |
| `keywords` | jsonb | 中文关键词数组（猎聘用） |
| `keywords_en` | jsonb | 英文关键词数组（领聘用） |
| `competitiveness` | jsonb | 竞争力证据数组（打分时唯一允许引用的证据源之一） |
| `gaps` | jsonb | 缺口数组 |
| `confirmed` | boolean | **true 才允许采集** |
| `is_active` | boolean | 同一用户仅一条 true |
| `created_at` / `updated_at` | timestamptz | |

`target_profile` 结构（键名固定）：

```json
{
  "roles": ["string"],
  "level": "string",
  "industries": ["string"],
  "cities": ["string"],
  "cities_en": ["string"]
}
```

### 2.2 `jobs`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | bigint PK | |
| `owner_id` | text | |
| `company` | text | |
| `position` | text | 岗位名原文（含"招聘"等前缀，规范化在比对时做） |
| `jd_summary` | text | ≤300 字摘要 |
| `salary` | text | 缺失填 `面议` |
| `location` | text | 缺失填 `未提及` |
| `source_url` | text | 职位详情链接，可为 null |
| `jd_text` | text | 原始 JD（仅手动粘贴路径写入） |
| `match_score` | integer | 0-100，null 表示未打分 |
| `match_reason` | text | ≤30 字：主依据 + 最大缺口 |
| `status` | text | 见状态机 |
| `platform` | text | `猎聘` / `领英` |
| `created_at` / `updated_at` | timestamptz | |

### 2.3 `jobs.status` 状态机

```
                    ┌──────────── 不合适 ◀── 用户点「不投了」
                    │                 │
待确认 ──授权──▶ 待投递 ──手动投递──▶ 已投递 ──平台反馈──▶ 已查看 ──▶ 面试中
   ▲                 ▲                 │                      │
   └──「↩ 移回待确认」─┴─────────────────┴──────────────────────┘
```

- 只允许通过 UI 动作变更，**不允许任务侧把老岗位重置为 `待确认`**
- `不合适`、`已投递`、`已查看`、`面试中` 都属于「已存在」，采集时一律跳过

### 2.4 `job_events`

| 字段 | 说明 |
|---|---|
| `job_id` | 关联 `jobs.id` |
| `event_type` | `授权投递` / `已投递` / `状态变化：A→B` / `放弃投递` / `恢复待确认` |
| `note` | 说明，`状态变化` 类固定写 `猎聘官方状态同步` |
| `created_at` | |

### 2.5 `agent_tasks`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | uuid PK | |
| `owner_id` | **text**（不是 uuid，`auth.uid()` 返回 text） | |
| `type` | text | `collect_now` / `collect_scheduled` |
| `status` | text | `pending` / `processing` / `done` / `failed` / `merged` |
| `note` | text | 见状态口径 |
| `requested_at` | timestamptz | 默认 now() |
| `processed_at` | timestamptz | |

**状态口径（写入方必须遵守）**

| status | note 格式 |
|---|---|
| `processing` | `定时采集运行中` / `手动采集运行中` |
| `done` | `猎聘入库N1条/领英入库N2条/重复M个/清理重复C条/打分K条` |
| `failed` | `失败原因：<≤40 字一句话>` |
| `merged` | `已合并：<一句话说明>` |

---

## 3. 建库步骤（顺序不可调换）

1. `CREATE TABLE`（4 张，见 `scripts/schema.sql` 第 1 段）
2. `GRANT SELECT, INSERT, UPDATE, DELETE ON <table> TO authenticated, anon;`（**漏了会得到形似"策略失效"的 42501**）
3. `ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;`
4. `CREATE POLICY <table>_owner ON <table> FOR ALL USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());`
5. 序列权限（bigint 自增表）：`GRANT USAGE, SELECT ON SEQUENCE <table>_id_seq TO authenticated, anon;`

### 3.6 身份注入（非 WorkBuddy 通道必做，WorkBuddy 通道可跳过）

上面 1-5 步只保证**读隔离**（浏览器端 OAuth → `auth.uid()` → RLS）。若你在 WorkBuddy 之外复现（Claude Code / Codex 直连数据库），**写隔离**必须额外补三步，否则 Agent 将以特权身份跨用户读写：

1. 建**非特权**角色 `job_agent`（`LOGIN`，只给 4 张表的 CRUD + 序列 USAGE）——**禁止**超级用户、`service_role`、带 `BYPASSRLS` 的角色
2. 实现 `auth.uid()` 等价物：`SELECT nullif(current_setting('app.uid', true), '')`
3. 四张表全部 `ALTER TABLE <t> FORCE ROW LEVEL SECURITY;`（否则表 owner 绕过 RLS）

Agent 每次写库必须包在事务里：

```sql
BEGIN;
SELECT set_config('app.uid', '<owner_id>', true);   -- 第三参 true = 仅本事务
-- … 读写语句（无需手写 WHERE owner_id，RLS 会限行）
COMMIT;
```

**必须 `set_config(..., true)` 或 `SET LOCAL`**；用 `SET` 会污染会话，连接池复用时造成跨用户串号。

验收：`set_config('app.uid','user-A')` 后 `count` 身份 B 的行，**必须返回 0**。

完整 SQL 见 `scripts/auth-isolation.sql`，原理见 `docs/09-portability-auth.md`。

---

## 4. 前端实现要点（`app/index.html`）

必须存在且行为一致的函数/构件：

| 能力 | 实现要点 |
|---|---|
| 简历解析 | `docx → mammoth`；`pdf → pdf.js`；`md/txt → 直读`；`img → OCR`。**全部浏览器本地完成**，不调外部解析服务 |
| 脱敏 | 解析后立即正则替换手机号/邮箱/身份证/详细住址为占位符，再送 LLM |
| LLM JSON | 统一 `llmJSON(system, user)`：120s 超时 + `JSON.parse` try/catch + 失败重试 1 次；请求期间禁用输入框并显示「AI 正在思考」 |
| 去重键 | `normTxt()`：全角转半角 → 删「招聘/诚聘/急招/热招/岗位名称/职位名称/岗位/职位」→ 删空格与标点 → 小写；`dupKey(j) = normTxt(company) + '|' + normTxt(position)` |
| 列表折叠 | `dedupeList(list)`：按 `dupKey` 分组，组内 `bestFirst` 排序取首条；三页签与岗位池渲染前都要过它 |
| 排序规则 | `bestFirst`：状态优先（已投递>面试中>已查看>待投递>待确认>不合适）→ 匹配度降序 → 有链接优先 → id 升序 |
| 批量授权 | 勾选 → 逐条 `authorize()`：`status='待投递'` + 写 `job_events(授权投递)` + `window.open(source_url)` |
| 手动投递 | `markSent()`：`status='已投递'` + 写事件 |
| 一键去重 | `dedupeAll()`：分组 → 二次确认（列出前 5 组）→ 迁移 `job_events` → 删除重复行 |
| 采集触发 | 写 `agent_tasks(type='collect_now', status='pending')`，提示"平均 30 分钟内执行" |
| 运行记录 | 读 `agent_tasks` 最近 20 条，渲染四态徽章：进行中 / 已完成 / 已失败（显示原因）/ 已合并 |
| 看板刷新 | 定点 08:40 / 10:00 / 18:40 / 20:00 + `visibilitychange` 立即同步 + 手动刷新按钮；**不要用盲轮询** |

---

## 5. 三个定时任务（prompt 全文见 `docs/05-automations.md`）

| 任务 | 频率 | 职责 |
|---|---|---|
| 采集（早） | `FREQ=DAILY;BYHOUR=8;BYMINUTE=0` | 猎聘 + 领英采集 → 全状态查重入库 → 打分 → 登记 |
| 采集（晚） | `FREQ=DAILY;BYHOUR=18;BYMINUTE=0` | 同上 |
| 检查点 | `FREQ=HOURLY;INTERVAL=1` | ① 看门狗切断超时运行 ② 消费 `collect_now` 请求 |

任务执行顺序（每个采集任务内部）：

```
0.   读画像（无 confirmed 画像 → 发提醒后退出，不登记）
0.4  防重复补跑守卫：先清理 >2h 的 processing，再查 90 分钟内是否已有 processing，有则静默退出
0.5  登记 run（collect_scheduled / processing）
1.   猎聘采集（3 个中文关键词，写 tmp JSON）
2.   领英采集（3 个英文关键词，条件执行，见第 6 节）
3.   写入岗位池：全状态查重 → INSERT 新增 / UPDATE 补字段 → 入库后自检 count>1 并清理
3.5  JEV 打分（仅本轮新增且 status='待确认'）
4.   收尾：更新 run 状态为 done/failed + note；推送汇总
```

**查重规则（第 3 步，最易写错，务必逐字实现）**

1. 取存量：`SELECT id, company, position, source_url, salary, location, status, match_score FROM jobs WHERE owner_id='<uid>' ORDER BY id LIMIT 2000` —— **不加 status 过滤**
2. 岗位键 `normTxt(company) + '|' + normTxt(position)`；链接键 `source_url` 去掉 `?`/`#` 及其后内容并小写
3. 岗位键命中存量或命中本轮已入库 → 跳过（`M+1`），**即使链接/平台/薪资不同**
4. 链接键命中 → 跳过
5. 都未命中 → `INSERT`，并把岗位键加入本轮集合；单轮上限 120 条
6. 存量有同岗位但缺链接 / 薪资空 / 地点空 → **不新增**，`UPDATE ... COALESCE` 补字段，**不动 status**
7. 入库后必跑 `GROUP BY company, position HAVING count(*)>1`，有结果则按 `bestFirst` 保留一条，其余先迁 `job_events` 再删

---

## 6. 领英采集的前置门禁（**不满足必须跳过，禁止降级**）

在执行领英段之前，必须依次验证以下两条硬断言，全部通过才允许继续（第三条为辅助判断，不参与门禁）：

| # | 断言 | 通过条件 | 不通过时 |
|---|---|---|---|
| 1（硬） | 出口 IP 地理判定 | `curl -s https://www.cloudflare.com/cdn-cgi/trace` 中 `loc` ≠ `CN` | 跳过领英，记 `失败原因：出口IP被判CN` |
| 2（硬） | 领英搜索页状态 | `https://www.linkedin.com/jobs/search/?keywords=<kw>` 返回 **200** | 302 到 `linkedin.cn` → 记 `失败原因：领英重定向linkedin.cn` |
| 3（辅助） | 出口 IP vs 本机 IP | 仅作提示 | **不要**用它做门禁：TUN 全局模式下两者相同属正常 |

补充约束：

- 页面出现 `451` / authwall / 验证码 → 立即停止，**不重试、不绕过**
- 每轮 ≤ 3 关键词 × 1 页 × 25 条；词间 30-60s 随机
- 不翻页、不滚动、不点开职位详情、不点 Easy Apply
- 卡片缺链接时可用「岗位名 + 公司名」精确搜索补齐一次；仍缺则留空并在 `jd_summary` 标注

**绝不允许**：检测到重定向后"改成直连也能打开"就继续抓 —— `linkedin.cn` 是中国区内容，数据不可用。

---

## 7. 打分规格（JEV）

```
score = round(0.35*技能 + 0.15*行业 + 0.20*职级经验 + 0.15*薪资地点 + 0.15*发展契合)
```

- 每个维度 0-100，只能引用 `competitiveness` / `target_profile` / 简历原文中的证据
- 证据不足 → 该维度取保守中间值（50 上下），不得凭想象补
- 硬冲突（城市不允许 / 职级跨度过大 / 行业完全无关）→ 总分 < 50
- `match_reason` ≤30 字，格式：`得分主依据 + 最大缺口`
- 输出必须是合法 JSON：`{"results":[{"index":1,"score":85,"reason":"..."}]}`

---

## 8. 验收脚本

```bash
# 网络
bash scripts/check-network.sh

# 数据一致性（在云数据库执行）
# 1) 不应存在重复岗位
SELECT company, position, count(*) FROM jobs GROUP BY 1,2 HAVING count(*)>1;
# 2) 不应存在超过 2 小时的 processing
SELECT id FROM agent_tasks WHERE status='processing' AND requested_at < now() - interval '2 hours';
# 3) 已投递岗位必须都有事件
SELECT j.id FROM jobs j LEFT JOIN job_events e ON e.job_id=j.id
 WHERE j.status='已投递' AND e.id IS NULL;
```

---

## 9. 变更禁区

以下行为属于**破坏产品边界**，任何复刻/二次开发都不应引入：

1. 自动点击投递、自动填表、自动给 HR 发消息
2. 索要或存储第三方平台账号密码
3. 绕过验证码 / 人机验证 / 登录墙
4. 关闭 RLS 或把策略放宽到跨用户可读
5. 采集时把已有岗位重置为 `待确认`（会让人重复投递）
6. 在领英重定向后改走直连继续抓取
7. 用盲轮询（如每 20 分钟）替代事件对齐刷新
