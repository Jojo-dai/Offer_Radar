#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""已决岗位回流审计（只读，不删不改）

回答一个问题：**岗位池（待确认）里，还有没有我已经点过「不投 / 授权投递 / 已投递」的岗位副本？**

判定规则必须与前端 `decidedIndex()` 保持一致（app/index.html）：
  1. 严格键：公司 + 岗位 归一化（去招聘类词、空格、标点、全半角）后相等
  2. 宽松键：严格键基础上去掉 (MJ编号) / 4 位以上数字 / 末尾城市，兼容平台标题差异
  3. 链接：去参数、去锚点、去尾斜杠、小写后相等
改其中任何一处，另一处必须同步，并跑 `node scripts/test-decisions.js`。

用法：
  python scripts/audit-decisions.py            # 有回流风险 → 退出码 1
  python scripts/audit-decisions.py --json     # 机器可读
"""
import argparse
import json
import re
import sys
from pathlib import Path

WS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WS / ".workbuddy" / "tmp"))
import dbq  # noqa: E402

OWNER = "wb:Cndyfv_eOir07ck0FARtAjlvVeet"
PENDING = "待确认"

PUNC = re.compile(r"[（）()【】\[\]{}<>·,，.。、/\\|\-—_~!！?？:：;；'\"“”‘’+*&#@]")
NOISE = re.compile(r"招聘|诚聘|急招|热招|岗位名称|职位名称|岗位|职位")
CITY_TAIL = re.compile(
    r"(上海|北京|深圳|广州|杭州|苏州|南京|成都|武汉|西安|天津|重庆|中国|"
    r"china|shanghai|beijing|shenzhen|guangzhou|hangzhou|suzhou|nanjing|chengdu|wuhan)$")


def fullwidth_to_half(s):
    return "".join(chr(ord(ch) - 0xFEE0) if 0xFF01 <= ord(ch) <= 0xFF5E else ch for ch in str(s or ""))


def norm_txt(s):
    s = fullwidth_to_half(s)
    s = NOISE.sub("", s)
    s = re.sub(r"[\s\u3000]", "", s)
    return PUNC.sub("", s).lower()


def strict_key(r):
    return norm_txt(r["company"]) + "|" + norm_txt(r["position"])


def loose_key(r):
    c = norm_txt(r["company"])
    p = re.sub(r"mj\d+", "", norm_txt(r["position"]))
    p = re.sub(r"\d{4,}", "", p)
    prev = None
    while p != prev:
        prev, p = p, CITY_TAIL.sub("", p)
    if not c and not p:
        return None
    return c + "|" + p


def url_key(u):
    return re.sub(r"[?#].*$", "", str(u or "").strip()).rstrip("/").lower()


def fetch_all():
    rows, last = [], 0
    while True:
        chunk = dbq.sql(
            "SELECT id,company,position,status,source_url,created_at FROM jobs "
            "WHERE owner_id='%s' AND id>%d ORDER BY id LIMIT 900" % (OWNER, last),
            "read", as_json=True)
        if isinstance(chunk, str):
            raise SystemExit("查询失败：" + chunk[:300])
        if not chunk:
            break
        rows.extend(chunk)
        last = chunk[-1]["id"]
        if len(chunk) < 900:
            break
    return rows


def check(rows):
    """返回 (待确认, 已决, 回流清单)，供真实审计与自检共用"""
    decided = [r for r in rows if r["status"] != PENDING]
    pending = [r for r in rows if r["status"] == PENDING]
    s_keys = {strict_key(r) for r in decided}
    l_keys = {loose_key(r) for r in decided if loose_key(r)}
    u_keys = {url_key(r["source_url"]) for r in decided if url_key(r["source_url"])}
    leaks = []
    for r in pending:
        why = []
        if strict_key(r) in s_keys:
            why.append("同名岗位")
        elif loose_key(r) and loose_key(r) in l_keys:
            why.append("同名岗位（编号/城市差异）")
        if url_key(r["source_url"]) and url_key(r["source_url"]) in u_keys:
            why.append("同一职位链接")
        if why:
            leaks.append({"id": r["id"], "company": r["company"], "position": r["position"],
                          "created_at": r.get("created_at"), "why": why})
    return pending, decided, leaks


def self_test():
    """负向验证：规则必须能抓到「已决岗位的副本」，同时不能误伤无关岗位"""
    J = lambda i, c, p, s, u=None: {"id": i, "company": c, "position": p, "status": s, "source_url": u}
    cases = [
        ("同名副本", [J(1, "Deloitte", "SAP Consultant", "不合适"), J(2, "Deloitte", "SAP Consultant", PENDING)], 1),
        ("编号差异", [J(3, "佛吉亚", "FP&A Supervisor", "不合适"),
                  J(4, "佛吉亚", "FP&A Supervisor (MJ003311)", PENDING)], 1),
        ("城市后缀", [J(5, "PepsiCo", "Commercial Control Manager", "不合适"),
                  J(6, "pepsico", "commercial control manager（上海）", PENDING)], 1),
        ("同链接", [J(7, "Visa", "Finance Manager", "已投递", "https://x.com/j/1?ref=a"),
                 J(8, "Visa", "Finance Manager II", PENDING, "https://x.com/j/1/")], 1),
        ("正常岗位不误伤", [J(9, "巴斯夫", "财务分析经理", "不合适"), J(10, "西门子", "SAP 顾问", PENDING)], 0),
        ("撤销后回池", [J(11, "罗氏", "Finance IT", PENDING)], 0),
        ("授权投递", [J(12, "联合利华", "FP&A Manager", "待投递"), J(13, "联合利华", "FP&A Manager", PENDING)], 1),
    ]
    pass_n = fail_n = 0
    for label, data, want in cases:
        _, _, leaks = check(data)
        if len(leaks) == want:
            pass_n += 1
            print("  ✓ %s（命中 %d，期望 %d）" % (label, len(leaks), want))
        else:
            fail_n += 1
            print("  ✗ %s（命中 %d，期望 %d）" % (label, len(leaks), want))
    print("\n自检通过 %d / %d" % (pass_n, pass_n + fail_n))
    return 1 if fail_n else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--self-test", action="store_true", help="不连库，用内存样本验证判定规则本身有效")
    a = ap.parse_args()

    if a.self_test:
        return self_test()

    rows = fetch_all()
    pending, decided, leaks = check(rows)

    if a.json:
        print(json.dumps({"total": len(rows), "pending": len(pending), "decided": len(decided),
                          "leaks": leaks}, ensure_ascii=False, indent=1))
    else:
        print("全库 %d 条｜待确认 %d｜已决 %d" % (len(rows), len(pending), len(decided)))
        if not leaks:
            print("✅ 没有已决岗位回流：岗位池里不存在你点过不投/已投递的副本")
        else:
            print("❌ 发现 %d 条已决岗位仍在待确认池（前端会隐藏，但数据应清理）：" % len(leaks))
            for x in leaks[:30]:
                print("   id=%s  %s | %s  ← %s" % (x["id"], x["company"][:20], x["position"][:32], "/".join(x["why"])))
            if len(leaks) > 30:
                print("   …其余 %d 条略" % (len(leaks) - 30))
    return 1 if leaks else 0


if __name__ == "__main__":
    sys.exit(main())
