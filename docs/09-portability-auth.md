# 09 · 跨 Agent 复现：身份与数据隔离

> 本文回答三个问题：
> 1. 打包之后交给 Claude / Codex 复现，具体怎么落地？
> 2. 上传的简历数据凭什么隔开？会不会被别的 Agent 看到？
> 3. 现在的隔离靠的是 WorkBuddy 账号体系，换成 Codex 之后靠什么？

---

## 0. 一句话结论

**设计上，Agent 只碰画像字段，不碰简历原文。** 区别在于这条规则是"约定"还是"强制"：

| 路径 | 简历原文对 Agent 可见吗 | 靠什么保证 |
|---|---|---|
| A. WorkBuddy | 可见（同一特权通道），但任务 prompt 只读画像字段 | **约定** —— prompt 里从不 SELECT `resume_text` |
| B. 自建 PG | 不可见 | **强制** —— `REVOKE SELECT (resume_text)` + 只给 `profiles_safe` 视图 |
| C. 纯本地 | 可见（同 OS 用户） | **无法保证** —— 这是它的固有弱点 |

### 简历数据到底落在哪

| 位置 | 内容 | 谁能读 |
|---|---|---|
| PostgreSQL `profiles.resume_text` | 解析 + **PII 脱敏后**的文本（≤20000 字） | 只有该行 `owner_id` 对应的登录用户（RLS 强制） |
| 浏览器内存 | 上传瞬间的原始文件与解析中间态 | 只有当前浏览器标签页 |

原始 docx / pdf / 图片**不上传**，全部在浏览器本地解析；但脱敏后的文本会存进你自己的云库。这一点必须说清楚——它不是"只在本地"。

所以复现时要决定的**不是**"Agent 怎么拿到简历"，而是——**谁以什么身份写库、以什么权限读库**。读链路天然隔离，写链路和列级权限才是需要设计的地方。

---

## 1. 先看清现状：这个项目其实有两条独立身份链

| | 浏览器读链路 | Agent 写链路（定时任务） |
|---|---|---|
| 调用方式 | `cloud.database.from('jobs')` | `mcp__…__workbuddy_cloudservice_db_exec_sql` |
| 携带凭证 | `publishableKey` + OAuth 会话 JWT | `applicationId` |
| 身份来源 | JWT 的 `sub` → PG 的 `auth.uid()` | 由工具内部决定，**不在本项目控制范围内** |
| 隔离强制力 | **强制**（数据库层 RLS，篡改前端也越不过） | **约定**（靠 prompt 里手写 `WHERE owner_id='<owner_id>'`） |

### 为什么能判断"写链路是约定式的"

定时任务的生产 prompt 里，几乎每条 SQL 都显式带着 `owner_id`：

```sql
SELECT … FROM jobs WHERE owner_id='<owner_id>' ORDER BY id LIMIT 2000
INSERT INTO agent_tasks (owner_id, …) VALUES ('<owner_id>', …)
```

如果这条通道本身会按调用者身份自动限行，这层手写限定就是多余的。**它之所以存在，说明这条通道具备跨用户能力。**

### 这意味着什么（诚实说明）

- **单用户自用**：没有风险。库里只有你自己的数据，"越权"无处可去。
- **要给别人用 / 要公开发布**：必须把写链路从"靠 prompt 自律"升级成"数据库层强制"。做法见第 4 节。

---

## 2. 三条复现路径，选一条

| 路径 | 适用 | 改造量 | 隔离强度 | 简历数据在哪 |
|---|---|---|---|---|
| **A. 留在 WorkBuddy** | 用 WorkBuddy / 同类平台 | 只换 3 个占位符 | 读强制 + 写约定 | 你账号下的云库 |
| **B. 换 Cloud（Supabase / 自建 PG）** | 用 Claude Code、Codex 自建一套 | 中（改身份注入） | 读强制 + **写强制** | 你自己账号下的云库 |
| **C. 纯本地单机** | 只要单机自用、不想接云 | 小（换存储层） | OS 账户 + 文件权限 | 本机磁盘 |

三条路径**共用的部分**：表结构、状态机、去重规则、JEV 打分、工作边界。区别只在"存储 + 身份"这一层。

---

## 3. 路径 A：留在 WorkBuddy（零改造）

复现者只需要替换三个占位符：

```js
const publicConfig = {
  endpoint: 'https://<your-app>.app.workbuddy.host',   // ① 你的应用地址
  oauthRelayBaseUrl: 'https://www.workbuddy.cn/v2/as/genie-baas/oauth',
  publishableKey: '<YOUR_PUBLISHABLE_KEY>'             // ② 你的 publishable key
};
```

③ 三个定时任务的 `applicationId` 换成自己的 `wbapp_...`。

身份链自动继承：登录走 OAuth → JWT → `auth.uid()` → RLS。

**限制**：绑定 WorkBuddy 账号体系。Codex 在本地跑，拿不到这个 OAuth 回调，所以走不通这条路。

---

## 4. 路径 B：换 Cloud —— 把"约定"升级成"强制"（Codex 走这条）

核心思路：**让 Agent 用一个没有特权的数据库角色，并在事务里注入"当前是谁"**，这样 `auth.uid()` 照常工作，**四张表的 RLS 策略一行都不用改**。

### 4.1 建一个非特权 Agent 角色

```sql
-- 关键：不要用 postgres / 超级用户 / 带 BYPASSRLS 的角色
CREATE ROLE job_agent LOGIN PASSWORD '<强密码>';
GRANT CONNECT ON DATABASE <your_db> TO job_agent;
GRANT USAGE ON SCHEMA public TO job_agent;

GRANT SELECT, INSERT, UPDATE, DELETE ON profiles, jobs, job_events, agent_tasks TO job_agent;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO job_agent;

-- 明确不给：CREATE / DROP / TRUNCATE / ALTER
```

### 4.2 自己实现 `auth.uid()`，让它读会话变量

WorkBuddy / Supabase 的 `auth.uid()` 读 JWT。Codex 直连没有 JWT，所以自己实现一个等价物：

```sql
CREATE SCHEMA IF NOT EXISTS auth;

CREATE OR REPLACE FUNCTION auth.uid() RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('app.uid', true), '')
$$;
```

> 若目标库已有 `auth.uid()`（Supabase），**不要覆盖**，直接跳过 4.2，改用第 4.4 节的 Supabase 变体。

### 4.3 强制 RLS 也约束表 owner（最容易被忽略的一步）

PostgreSQL 的默认行为：**表的 owner 绕过 RLS**。如果你的表是用 `job_agent` 之外的角色建的，问题不大；但只要 owner 和连接角色一致，RLS 就形同虚设。

```sql
ALTER TABLE profiles    FORCE ROW LEVEL SECURITY;
ALTER TABLE jobs        FORCE ROW LEVEL SECURITY;
ALTER TABLE job_events  FORCE ROW LEVEL SECURITY;
ALTER TABLE agent_tasks FORCE ROW LEVEL SECURITY;
```

### 4.4 Agent 每次写库前，在事务内注入身份

```sql
BEGIN;
SELECT set_config('app.uid', '<owner_id>', true);   -- true = 仅本事务有效
-- 之后所有读写都受该身份约束，且 INSERT 不写 owner_id 也能命中 DEFAULT auth.uid()
INSERT INTO jobs (company, position, …) VALUES (…);
COMMIT;
```

**必须是 `SET LOCAL` / `set_config(..., true)`，不能是 `SET`。** 原因见第 8 节第 ① 条。

Supabase 变体（改用自定义 JWT，而不是会话变量）：用项目的 JWT secret 签一个 `{"role":"authenticated","sub":"<user_uuid>"}` 的 token 给 Agent 用。**绝不要用 `service_role` key** —— 它绕过 RLS。

### 4.5 越权自检（复刻验收必做）

模拟"身份 A 去读身份 B 的数据"，**必须返回 0 行**：

```sql
BEGIN;
SELECT set_config('app.uid', 'user-A', true);
SELECT count(*) FROM jobs WHERE owner_id = 'user-B';   -- 期望 0
ROLLBACK;
```

如果返回了非 0，说明 4.1～4.3 有一处没生效，不要继续上线。

---

## 5. 路径 C：纯本地单机（Codex 最省事的一条）

数据落在本机，隔离边界变成**操作系统账户 + 文件权限**：

| 项 | 做法 |
|---|---|
| 存储 | SQLite 单文件（`~/.job-agent/data.db`）或浏览器 IndexedDB |
| 隔离 | `chmod 600`（macOS/Linux）或仅当前用户可读的 ACL（Windows） |
| Agent 身份 | 就是"当前 OS 用户"，不需要额外的凭证体系 |
| 简历读取 | Agent 进程与数据同属一个 OS 用户，天然可读——**这正是它的弱点** |

**代价**：多设备不同步、备份靠用户自己、任何能在该账户下执行的程序都能读到库文件。适合纯个人单机。

---

## 6. Claude / Codex 复现执行清单

按顺序做，每步可验证：

1. 读 `AGENTS.md` 第 0 节「复刻完成判据」，先明确目标形态
2. 选路径（第 2 节表格），**A / B / C 只选一条**，不要混
3. 建库：执行 `scripts/schema.sql` 四段（建表 → GRANT → RLS → 巡检）
4. 若选 B：额外执行第 4.1～4.3 节（非特权角色 + `auth.uid()` + `FORCE RLS`）
5. 配置身份注入：Agent 每次开事务先 `set_config('app.uid', …, true)`
6. 跑第 4.5 节越权自检，**必须 0 行**
7. 替换 `app/index.html` 的 `publicConfig` 三个占位符
8. 按 `AGENTS.md` 第 8 节验收脚本逐条过

---

## 7. 简历字段的额外保护（可选加固）

`resume_text` 是全库最敏感的字段（完整工作经历 + 联系方式）。上面所有机制已经保证了"别人读不到"，如果还想加一层**列级**限制：

### 做法：给 Agent 一个不含简历原文的视图

```sql
CREATE VIEW profiles_safe AS
  SELECT id, owner_id, target_profile, keywords, keywords_en,
         competitiveness, gaps, is_active, confirmed, created_at
  FROM profiles;          -- 故意不含 resume_text / chat_log

GRANT SELECT ON profiles_safe TO job_agent;
REVOKE SELECT (resume_text) ON profiles FROM job_agent;
```

理由：采集与打分**只用到画像字段，不需要简历原文**。Agent 侧永远不该读原文，这是最小权限原则的直接应用。

> PostgreSQL 没有"列级 RLS"，只有列级 `GRANT`。所以列级限制必须靠 `REVOKE` + 视图，不能靠策略。

更激进的做法：简历原文不落库，只在浏览器解析后把**结构化画像**写进 `profiles`。代价是重新走流程要重传简历。

---

## 8. 五个一定会踩的坑

### ① 用 `SET` 而不是 `SET LOCAL` → 连接池串号

`SET` 是**会话级**的。Agent 若用连接池（pgBouncer、大多数 ORM），同一连接会被不同请求复用，上一个用户设的 `app.uid` 会残留在下一个请求里——**跨用户串数据**。

```sql
-- 错：污染整个会话，且连接池复用时泄漏
SET app.uid = 'user-A';

-- 对：只在当前事务内有效，事务结束自动清空
BEGIN; SELECT set_config('app.uid','user-A', true); …; COMMIT;
```

### ② 给 Agent 用超级用户 / `service_role` / `BYPASSRLS` 角色

RLS 对这几类身份**完全不生效**。一旦用它，前面所有策略等于没写——隔离归零。这是最危险也最常见的一步错。

### ③ 忘了 `FORCE ROW LEVEL SECURITY`

表 owner 默认绕过 RLS。策略写对了、GRANT 也给了，但连接角色恰好是表 owner，看起来"能读到别人的数据"。加 `FORCE` 即可。

### ④ `owner_id` 声明成 uuid

`auth.uid()` 返回 text。`agent_tasks.owner_id` 若写成 uuid，插入直接报类型错。四张表统一 text。

### ⑤ 只做 RLS 不做 GRANT

会得到 `42501 permission denied`，形似"策略配错"，实际是权限没给。两道门都得开。

---

## 9. 一页速查

```
简历数据在哪？      只在 profiles.resume_text + 浏览器内存。Agent 不持有。
浏览器怎么隔离？    OAuth JWT → auth.uid() → RLS 强制。篡改前端也越不过。
Agent 怎么隔离？    A: 平台工具身份（约定式）
                    B: 非特权角色 + set_config('app.uid', …, true) + FORCE RLS（强制式）
                    C: OS 账户 + 文件权限
Codex 用哪条？      B 或 C。B 要自己实现 auth.uid()；C 最省事但不跨设备。
千万别做什么？      别用超级用户 / service_role；别用 SET；别忘 FORCE RLS。
怎么验证？         set_config 成 user-A 去 count user-B 的行，必须 0。
```

---

**相关文档**：[`04-database.md`](04-database.md)（表结构与策略原因） · [`02-boundaries.md`](02-boundaries.md)（工作边界） · [`05-automations.md`](05-automations.md)（任务侧如何写库）
