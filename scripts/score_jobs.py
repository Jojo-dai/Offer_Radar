#!/usr/bin/env python3
"""JEV 打分器（唯一权威版本，2026-11-09 固化进仓库）

背景：此前每轮采集都在 .workbuddy/tmp 里临时改一份 scoreN.py，规则漂移导致
同一个 bug 反复出现——最典型的是猎聘卡片标题带「招聘」前缀（如
「招聘数据产品经理」），被 HR 硬冲突正则 `招聘|hrbp|...` 命中，整批岗位
一律判 26 分沉底。2026-11-09 那一轮 45 条猎聘岗位全部中招。

本脚本把它固化为唯一口径：
1. 打分前先剥掉标题的「招聘」前缀（展示与判定同源）；
2. HR 硬冲突只匹配真正的招聘/HR 岗位，不再匹配裸前缀；
3. 命中 SAP/预算/业财等主线词保底 70，不命中不扣分。

用法：
  python job-apply-agent/scripts/score_jobs.py --since "2026-11-09 00:00"
  python job-apply-agent/scripts/score_jobs.py --ids 1063,1064,1065
  python job-apply-agent/scripts/score_jobs.py --unscored          # 补打未打分的
  python job-apply-agent/scripts/score_jobs.py --where "match_score=26 AND position LIKE '招聘%'" --dry-run
"""
import argparse
import json
import os
import re
import statistics
import sys
from pathlib import Path

WS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WS / ".workbuddy" / "tmp"))
import dbq  # noqa: E402

APP_OWNER = "wb:Cndyfv_eOir07ck0FARtAjlvVeet"

STRONG = r"预算|budget|fp&a|合并报表|业财|财务数字化|sap|bpc|经营分析|财务bp|管理会计|财务转型"

# 猎聘卡片标题的前缀噪音
PREFIX = re.compile(r"^[\[\(【（]?\s*(招聘|急聘|高薪|hot|new)\s*[\]\)】）]?\s*", re.I)

# 真正的 HR / 招聘岗位（注意：不能用裸「招聘」，会吃掉猎聘全量标题前缀）
HR_RE = re.compile(
    r"招聘(专员|经理|主管|顾问|助理|总监|负责人)|招聘官|hrbp|hr\s*bp|雇主品牌|人力资源|人事|"
    r"talent\s+acquisition|recruiter|recruitment",
    re.I,
)


def norm_position(raw):
    """剥掉猎聘标题前缀，供打分与展示复用。"""
    s = (raw or "").strip()
    for _ in range(2):  # 少数标题会叠两层前缀
        s2 = PREFIX.sub("", s)
        if s2 == s:
            break
        s = s2
    return s.strip()


def tier(p, comp):
    p = p.lower()
    # ---- 硬冲突：跨职能 ----
    if re.search(r"毒理|抗体|医药研发|药理|体外|adc|dmpk|临床|肾病|宠物用药|博士后|科研工程师", p):
        return 28, "职能硬冲突（生物医药研发方向）"
    if re.search(r"投资|研究员|equities|quant|quantitative|资产管理|债权|另类投资|行业研究", p):
        return 30, "职能硬冲突（投研/资管方向）"
    if HR_RE.search(p):
        return 26, "职能硬冲突（HR 方向）"
    if re.search(r"客服|办公室助理|职业经理(?!人)", p):
        return 22, "职能硬冲突（非目标职能）"
    if re.search(r"机械|结构工程师|agv|amr|电机|关节|仿真引擎|端到端算法|自动驾驶|adas|智驾|决策规划|vla算法", p):
        return 34, "技术方向偏离（汽车/机器人本体方向）"
    if re.search(r"地产|应用工程师（汽车零部件）", p):
        return 30, "行业硬冲突（地产/汽车零部件）"

    # ---- 校招 / 实习 ----
    if re.search(r"校招|应届|intern|实习|2027|graduate|云弧计划", p):
        return 25, "校招/实习岗与资深定位硬冲突"

    # ---- 职级过高 ----
    if re.search(r"director|cfo\b|vp\b|首席|p9|p10|技术负责人|架构负责人|全栈|团队负责人", p):
        return 44, "职级硬冲突（负责人/总监级或纯技术负责人）"
    if re.search(r"总监|head of|head,", p):
        return 46, "职级硬冲突（总监/Head 级），超出资深定位"

    # ---- 强相关：SAP / 预算 / 业财 ----
    if re.search(STRONG, p):
        if re.search(r"咨询|顾问|consultant|专家|specialist|analyst|分析师|manager|经理|lead", p):
            return 82, "SAP/预算/业财方向直接命中主线经验"
        return 74, "预算与业财方向命中主线，职级待确认"

    # ---- AI 产品 / 方案 ----
    if re.search(r"ai|agent|llm|大模型|智能体|genai", p) and re.search(
        r"产品|product|方案|solution|售前|咨询|顾问|专家|转型|fde|交付", p
    ):
        return 76, "AI 产品/方案方向命中企业级 AI 落地经验"
    if re.search(r"ai|agent|llm|大模型|智能体", p) and re.search(
        r"研发|开发|工程师|engineer|算法|架构|architect|scientist|researcher", p
    ):
        return 50, "AI 技术岗偏工程实现，弱于产品与方案职责"
    if re.search(r"产品经理|product manager|产品负责人|product owner", p):
        return 62, "产品经理方向契合，AI/企业级场景证据不足"
    if re.search(r"项目经理|project manager|program manager|项目专家|项目总监", p):
        return 58, "项目管理方向契合，行业与数字化场景待确认"
    if re.search(r"财务经理|财务主管|finance manager|controller|accounting|财务分析", p):
        return 58, "财务经理/核算分析岗相关，非数字化项目主线"
    return 46, "方向部分相关，关键信息不足"


def score_one(position, company=""):
    p = norm_position(position)
    s, w = tier(p, company)
    # 关键词保底只作用于「非硬冲突档」（55-69 分）。
    # 旧写法 s < 70 会把校招/实习（25 分）、职能硬冲突（22-46 分）一并顶到 70，
    # 导致 Intern 岗排进推荐前排（2026-11-13 实采发现：SAP 系升级项目实习生 被抬到 70）。
    if re.search(STRONG, p.lower()) and 55 <= s < 70:
        s, w = 70, "SAP/预算/业财关键词命中，技能维度按强相关计"
    if re.search(r"资深|senior|高级|sr\.", p, re.I) and s >= 60:
        s += 4
    if re.search(r"专员|分析师|analyst|assistant|助理|junior|初级", p, re.I) and s >= 55:
        s -= 6
    return max(10, min(95, s)), w[:30], p


def fetch(ids=None, since=None, unscored=False, where=None):
    conds = ["owner_id='%s'" % APP_OWNER]
    if ids:
        conds.append("id IN (%s)" % ",".join(str(int(i)) for i in ids))
    if since:
        conds.append("created_at >= '%s'" % since.replace("'", ""))
    if unscored:
        conds.append("match_score IS NULL")
    if where:
        conds.append("(%s)" % where)
    rows, last = [], 0
    while True:
        q = (
            "SELECT id, company, position, platform, match_score, left(coalesce(match_reason,''),30) AS reason "
            "FROM jobs WHERE %s AND id > %d ORDER BY id LIMIT 900" % (" AND ".join(conds), last)
        )
        chunk = dbq.sql(q, "read", as_json=True)
        if isinstance(chunk, str):
            raise SystemExit("查询失败：" + chunk[:300])
        if not chunk:
            break
        rows.extend(chunk)
        last = chunk[-1]["id"]
        if len(chunk) < 900:
            break
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids")
    ap.add_argument("--since")
    ap.add_argument("--unscored", action="store_true")
    ap.add_argument("--where")
    ap.add_argument("--fix-prefix", action="store_true", help="顺带把库里的「招聘」前缀剥掉")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    ids = [x for x in a.ids.split(",") if x.strip()] if a.ids else None
    if not any([ids, a.since, a.unscored, a.where]):
        raise SystemExit("至少给一个筛选条件：--ids / --since / --unscored / --where")

    rows = fetch(ids, a.since, a.unscored, a.where)
    if not rows:
        print("没有匹配的岗位")
        return

    final, changed = [], []
    for r in rows:
        s, w, clean = score_one(r["position"], r["company"])
        if s != r["match_score"] or w != (r["reason"] or ""):
            changed.append((r["id"], s, w))
        final.append((r["id"], s, w))

    print("待处理 %d 条，其中分数将变化 %d 条" % (len(rows), len(changed)))
    pos = {r["id"]: r for r in rows}
    for i, s, w in sorted(final, key=lambda x: -x[1])[:12]:
        print("  %3d  %-22s %-40s | %s" % (s, (pos[i]["company"] or "")[:22], norm_position(pos[i]["position"])[:40], w))
    if final:
        print("均分 %.1f，>=70 共 %d 条" % (statistics.mean(s for _, s, _ in final), sum(1 for _, s, _ in final if s >= 70)))

    if a.dry_run:
        print("--dry-run：未写库")
        return

    def q(t):
        return "'" + (t or "").replace("'", "''") + "'"

    for start in range(0, len(final), 200):
        part = final[start:start + 200]
        vals = ",".join("(%d,%d,%s)" % (i, s, q(w)) for i, s, w in part)
        sql = (
            "UPDATE jobs SET match_score=v.s, match_reason=v.w, updated_at=now() "
            "FROM (VALUES %s) AS v(id,s,w) WHERE jobs.id=v.id AND jobs.owner_id='%s'" % (vals, APP_OWNER)
        )
        res = dbq.sql(sql, "write", as_json=True)
        print("  写入 %d 条 -> %s" % (len(part), "ok" if not isinstance(res, str) else res[:200]))

    if a.fix_prefix:
        res = dbq.sql(
            "UPDATE jobs SET position = regexp_replace(position, '^(招聘|急聘)+', '') "
            "WHERE owner_id='%s' AND position ~ '^(招聘|急聘)'" % APP_OWNER,
            "write", as_json=True,
        )
        print("剥前缀 ->", "ok" if not isinstance(res, str) else res[:200])


if __name__ == "__main__":
    main()
