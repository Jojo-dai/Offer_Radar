# 04 · 数据模型与访问控制

建表脚本见 [`../scripts/schema.sql`](../scripts/schema.sql)。本文解释「为什么这样设计」。

## 四张表的关系

```
profiles (1) ─── 提供画像/关键词 ──▶ 采集任务
                                       │
                                       ▼
jobs (n) ──1:n──▶ job_events            agent_tasks（运行记录/请求队列，独立）
```

- `profiles` 与 `jobs` **不做外键关联**：岗位池是公共资产，换个画像不该导致岗位丢失
- `job_events.job_id` 指向 `jobs.id`，但**不加外键约束**（便于合并/清理重复时迁移事件）

## 关键设计决策

### 1. `owner_id` 统一用 `text`

`auth.uid()` 返回的是 **text**，不是 uuid。`agent_tasks.owner_id` 若声明为 uuid 会直接报类型错误（这是复刻时的第一个坑）。

### 2. `keywords` 与 `keywords_en` 分开存

- 猎聘吃中文词，领英吃英文词，两套词表**不能混用**
- 存成 jsonb 数组而非逗号字符串：任务侧可以直接 `jsonb_array_elements_text` 展开，避免分隔符歧义

### 3. `match_score` 允许 NULL

`NULL` 表示"未打分"，与 0 分（明确不匹配）语义不同。前端用 `match_score != null` 判断，排序时 `NULL` 排最后。

### 4. `status` 用中文字面量

`待确认 / 待投递 / 已投递 / 已查看 / 面试中 / 不合适`，直接可读。代价是不能用 enum 约束跨语言，收益是任务 prompt、SQL、UI 文案三处口径完全一致——这个项目里口径一致性比类型严格更重要。

### 5. `agent_tasks` 兼作队列与日志

同一个表承担两个职责：

- **队列**：`type='collect_now' AND status='pending'` → 每小时检查点消费
- **日志**：全部记录按 `requested_at DESC` 渲染成"运行采集记录"

好处是不需要额外的队列组件；代价是要靠 `status` 语义严格区分（所以状态口径必须逐字遵守）。

### 6. RLS 开关 + 显式 GRANT（两道独立的门）

PostgreSQL 里这是两步：

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON jobs TO authenticated, anon;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY jobs_owner ON jobs FOR ALL
  USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());
```

**只做 RLS 不做 GRANT**，会得到形似"策略配置错误"的 `42501 permission denied`——很容易误判成策略写错。反过来只 GRANT 不做 RLS，则所有用户可读彼此数据。

## 常见查询

```sql
-- 待确认岗位，按匹配度倒排（应用「最新岗位清单」用的就是这条）
SELECT * FROM jobs
 WHERE status = '待确认'
 ORDER BY match_score DESC NULLS LAST, id
 LIMIT 200;

-- 某岗位的完整事件历史
SELECT event_type, note, created_at
  FROM job_events WHERE job_id = $1
 ORDER BY created_at;

-- 最近 20 条运行记录
SELECT status, note, requested_at, processed_at
  FROM agent_tasks
 ORDER BY requested_at DESC LIMIT 20;

-- 投递转化漏斗
SELECT status, count(*) FROM jobs
 WHERE owner_id = auth.uid()
 GROUP BY status;
```

## 一致性巡检（复刻验收时全部应返回 0 行）

```sql
-- 1) 不应存在重复岗位
SELECT company, position, count(*) FROM jobs GROUP BY 1,2 HAVING count(*) > 1;

-- 2) 不应存在超过 2 小时仍 processing 的任务
SELECT id, type, requested_at FROM agent_tasks
 WHERE status = 'processing' AND requested_at < now() - interval '2 hours';

-- 3) 已投递岗位必须有事件
SELECT j.id FROM jobs j LEFT JOIN job_events e ON e.job_id = j.id
 WHERE j.status = '已投递' AND e.id IS NULL;

-- 4) 同一用户只应有一条激活画像
SELECT owner_id, count(*) FROM profiles WHERE is_active GROUP BY 1 HAVING count(*) > 1;
```
