-- ============================================================
-- 投递助手 · 路径 B：把「约定式隔离」升级为「强制式隔离」
-- 适用：非 WorkBuddy 通道（Claude Code / Codex / 自建部署）直连 PostgreSQL
-- 说明：四张表的 RLS 策略不需要修改，本脚本只补三件事：
--       ① 非特权 Agent 角色  ② auth.uid() 的等价物  ③ FORCE RLS
-- 用法：把 <your_db> / <强密码> 换成实际值后，按段落逐段执行
-- 警告：绝不要用 postgres 超级用户或带 BYPASSRLS 的角色跑 Agent
-- ============================================================


-- ------------------------------------------------------------
-- 第 1 段：非特权 Agent 角色
-- ------------------------------------------------------------
-- 若角色已存在，先 DROP ROLE job_agent;（需先回收已授予的权限）
CREATE ROLE job_agent LOGIN PASSWORD '<强密码>';

GRANT CONNECT ON DATABASE <your_db> TO job_agent;
GRANT USAGE  ON SCHEMA public        TO job_agent;

GRANT SELECT, INSERT, UPDATE, DELETE
  ON profiles, jobs, job_events, agent_tasks TO job_agent;

-- 序列：bigint IDENTITY 插入需要
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO job_agent;

-- 明确不给：CREATE / ALTER / DROP / TRUNCATE
-- 显式收回（防止继承自 PUBLIC 的默认权限）
REVOKE CREATE ON SCHEMA public FROM job_agent;


-- ------------------------------------------------------------
-- 第 2 段：auth.uid() 等价物（读会话变量，而不是 JWT）
-- ------------------------------------------------------------
-- 注意：Supabase 等平台已内置 auth.uid()，若已存在请跳过本段，
--       改用「自定义 JWT（role=authenticated, sub=<uuid>）」方案，
--       且绝不要用 service_role key。
CREATE SCHEMA IF NOT EXISTS auth;

CREATE OR REPLACE FUNCTION auth.uid() RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('app.uid', true), '')
$$;

GRANT USAGE ON SCHEMA auth TO job_agent;
GRANT EXECUTE ON FUNCTION auth.uid() TO job_agent;


-- ------------------------------------------------------------
-- 第 3 段：强制 RLS 也约束表 owner（最易漏）
-- ------------------------------------------------------------
-- PostgreSQL 默认：表 owner 绕过 RLS。不加 FORCE，策略形同虚设。
ALTER TABLE profiles    FORCE ROW LEVEL SECURITY;
ALTER TABLE jobs        FORCE ROW LEVEL SECURITY;
ALTER TABLE job_events  FORCE ROW LEVEL SECURITY;
ALTER TABLE agent_tasks FORCE ROW LEVEL SECURITY;


-- ------------------------------------------------------------
-- 第 4 段：Agent 侧的身份注入模板（每次写库都照这个写）
-- ------------------------------------------------------------
-- 必须是事务 + set_config(..., true)。
-- 用 SET 会污染会话，连接池复用时造成跨用户串数据。
--
-- BEGIN;
--   SELECT set_config('app.uid', '<owner_id>', true);
--   INSERT INTO jobs (company, position, platform, status, source_url)
--   VALUES ('某公司', '某岗位', '猎聘', '待确认', 'https://…');
--   -- owner_id 由 DEFAULT auth.uid() 自动填充，无需手写
-- COMMIT;
--
-- 读同理：
-- BEGIN;
--   SELECT set_config('app.uid', '<owner_id>', true);
--   SELECT id, company, position FROM jobs ORDER BY match_score DESC LIMIT 100;
--   -- 不加 WHERE owner_id，RLS 也会只返回本人的行
-- COMMIT;


-- ------------------------------------------------------------
-- 第 5 段：越权自检（复刻验收必须 0 行）
-- ------------------------------------------------------------
-- 5.1 身份 A 读不到身份 B 的数据
-- BEGIN;
--   SELECT set_config('app.uid', 'user-A', true);
--   SELECT count(*) AS should_be_zero FROM jobs WHERE owner_id = 'user-B';
-- ROLLBACK;
--
-- 5.2 未注入身份时，应当什么都读不到（而不是读到全部）
-- BEGIN;
--   SELECT count(*) AS should_be_zero FROM jobs;
-- ROLLBACK;
--
-- 5.3 不能写入别人的 owner_id（WITH CHECK 会拒绝，期望报错）
-- BEGIN;
--   SELECT set_config('app.uid', 'user-A', true);
--   INSERT INTO jobs (owner_id, company, position) VALUES ('user-B', 'X', 'Y');
-- ROLLBACK;
--
-- 5.4 确认 FORCE RLS 已生效（每张表应为 true）
-- SELECT relname, relrowsecurity, relforcerowsecurity
--   FROM pg_class
--  WHERE relname IN ('profiles','jobs','job_events','agent_tasks');


-- ------------------------------------------------------------
-- 第 6 段：可选加固 —— 给 Agent 一个不含简历原文的视图
-- ------------------------------------------------------------
-- 采集与打分只用画像字段，不需要简历原文。最小权限原则。
CREATE OR REPLACE VIEW profiles_safe AS
  SELECT id, owner_id, target_profile, keywords, keywords_en,
         competitiveness, gaps, is_active, confirmed, created_at
    FROM profiles;

GRANT SELECT ON profiles_safe TO job_agent;
REVOKE SELECT (resume_text) ON profiles FROM job_agent;
