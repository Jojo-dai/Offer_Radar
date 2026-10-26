-- ============================================================
-- 投递助手 · 全状态查重与清理
-- 语义：公司+岗位「规范化后」相同的记录视为同一岗位，
--       不论状态（待确认/待投递/已查看/已投递/面试中/不合适）都算已存在。
-- 保留规则：状态越靠前 > 匹配度更高 > 有链接 > id 更小
--         已投递 > 面试中 > 已查看 > 待投递 > 待确认 > 不合适
-- ============================================================


-- ------------------------------------------------------------
-- 1. 先看有哪些重复（只读，可反复执行）
-- ------------------------------------------------------------
WITH norm AS (
  SELECT id, company, position, status,
         regexp_replace(
           regexp_replace(lower(company), '招聘|诚聘|急招|热招|岗位名称|职位名称|岗位|职位', '', 'g'),
           '[^0-9a-z\u4e00-\u9fa5]', '', 'g') AS c,
         regexp_replace(
           regexp_replace(lower(position), '招聘|诚聘|急招|热招|岗位名称|职位名称|岗位|职位', '', 'g'),
           '[^0-9a-z\u4e00-\u9fa5]', '', 'g') AS p
  FROM jobs
)
SELECT c AS norm_company, p AS norm_position, count(*) AS cnt,
       array_agg(id ORDER BY id) AS ids,
       array_agg(DISTINCT status) AS statuses
FROM norm
GROUP BY c, p
HAVING count(*) > 1
ORDER BY cnt DESC, c;


-- ------------------------------------------------------------
-- 2. 找出每组应保留的记录与应删除的记录（只读，供人工核对）
-- ------------------------------------------------------------
WITH norm AS (
  SELECT id, owner_id, status, match_score, source_url,
         regexp_replace(
           regexp_replace(lower(company), '招聘|诚聘|急招|热招|岗位名称|职位名称|岗位|职位', '', 'g'),
           '[^0-9a-z\u4e00-\u9fa5]', '', 'g') AS c,
         regexp_replace(
           regexp_replace(lower(position), '招聘|诚聘|急招|热招|岗位名称|职位名称|岗位|职位', '', 'g'),
           '[^0-9a-z\u4e00-\u9fa5]', '', 'g') AS p
  FROM jobs
), grp AS (
  SELECT owner_id, c, p,
         (array_agg(id ORDER BY
            CASE status WHEN '已投递' THEN 0 WHEN '面试中' THEN 1 WHEN '已查看' THEN 2
                        WHEN '待投递' THEN 3 WHEN '待确认' THEN 4 WHEN '不合适' THEN 5 ELSE 6 END,
            match_score DESC NULLS LAST,
            (source_url IS NULL),
            id))[1] AS keep_id,
         count(*) AS n
  FROM norm
  GROUP BY owner_id, c, p
)
SELECT g.keep_id, array_agg(n.id ORDER BY n.id) AS all_ids, g.n
FROM grp g JOIN norm n ON n.owner_id = g.owner_id AND n.c = g.c AND n.p = g.p
WHERE g.n > 1
GROUP BY g.keep_id, g.n
ORDER BY g.n DESC;


-- ------------------------------------------------------------
-- 3. 一键清理（会改数据！先跑第 1、2 段确认结果）
--    动作：① 把重复记录上的 job_events 迁到保留记录
--          ② 删除重复的 jobs 记录
--    返回值：发现重复数 / 迁移事件数 / 删除岗位数
-- ------------------------------------------------------------
WITH norm AS (
  SELECT id, owner_id, status, match_score, source_url,
         regexp_replace(
           regexp_replace(lower(company), '招聘|诚聘|急招|热招|岗位名称|职位名称|岗位|职位', '', 'g'),
           '[^0-9a-z\u4e00-\u9fa5]', '', 'g') AS c,
         regexp_replace(
           regexp_replace(lower(position), '招聘|诚聘|急招|热招|岗位名称|职位名称|岗位|职位', '', 'g'),
           '[^0-9a-z\u4e00-\u9fa5]', '', 'g') AS p
  FROM jobs
), grp AS (
  SELECT owner_id, c, p,
         (array_agg(id ORDER BY
            CASE status WHEN '已投递' THEN 0 WHEN '面试中' THEN 1 WHEN '已查看' THEN 2
                        WHEN '待投递' THEN 3 WHEN '待确认' THEN 4 WHEN '不合适' THEN 5 ELSE 6 END,
            match_score DESC NULLS LAST,
            (source_url IS NULL),
            id))[1] AS keep_id,
         count(*) AS n
  FROM norm GROUP BY owner_id, c, p
), dup AS (
  SELECT n.id, g.keep_id
  FROM norm n JOIN grp g ON g.owner_id = n.owner_id AND g.c = n.c AND g.p = n.p
  WHERE g.n > 1 AND n.id <> g.keep_id
), ev AS (
  UPDATE job_events e SET job_id = d.keep_id FROM dup d WHERE e.job_id = d.id RETURNING e.id
), del AS (
  DELETE FROM jobs j USING dup d WHERE j.id = d.id RETURNING j.id
)
SELECT (SELECT count(*) FROM dup) AS duplicates_found,
       (SELECT count(*) FROM ev)  AS events_migrated,
       (SELECT count(*) FROM del) AS jobs_deleted;


-- ------------------------------------------------------------
-- 4. 清理后校验（应返回 0 行）
-- ------------------------------------------------------------
WITH norm AS (
  SELECT regexp_replace(
           regexp_replace(lower(company), '招聘|诚聘|急招|热招|岗位名称|职位名称|岗位|职位', '', 'g'),
           '[^0-9a-z\u4e00-\u9fa5]', '', 'g') AS c,
         regexp_replace(
           regexp_replace(lower(position), '招聘|诚聘|急招|热招|岗位名称|职位名称|岗位|职位', '', 'g'),
           '[^0-9a-z\u4e00-\u9fa5]', '', 'g') AS p
  FROM jobs
)
SELECT c, p, count(*) FROM norm GROUP BY c, p HAVING count(*) > 1;
