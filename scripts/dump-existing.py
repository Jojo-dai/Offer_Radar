#!/usr/bin/env python3
"""导出全状态存量岗位，供采集脚本做永久查重（2026-11-09 固化）。

为什么要单独一个脚本：云库单次查询上限 1000 行，超了直接报
`DATABASE_RESULT_EXCEED_MAX_ROWS`。岗位池在 2026-11-09 已到 1030 条，
再按「一次 SELECT 拉全量」的老写法，整轮采集会直接崩在查重这一步
（当天就是这样失败的）。这里改成按 id 键集分页，每页 900，取完为止，
岗位池涨到几万条也不会受影响。

输出：<workspace>/.workbuddy/tmp/existing-jobs.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

WS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WS / ".workbuddy" / "tmp"))
import dbq  # noqa: E402

OWNER = "wb:Cndyfv_eOir07ck0FARtAjlvVeet"
# 2026-11-24 修正：原来只导 8 列（缺 platform/jd_summary/match_reason/created_at/updated_at），
# 用这份 JSON 重建本地库时 platform 一律落到默认值「猎聘」，1107 条领英岗位全被显示成猎聘。
# 备份/迁移用的导出必须自带这几列，否则重建即失真。
COLS = ("id, company, position, source_url, salary, location, status, match_score, "
        "platform, jd_summary, match_reason, created_at, updated_at")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", type=int, default=300,
                    help="每页行数，默认 300（<1000）。13 列 × 900 行会超过 MCP 响应体积、稳定 500，故默认下调")
    ap.add_argument("--out", default=str(WS / ".workbuddy" / "tmp" / "existing-jobs.json"))
    a = ap.parse_args()
    if a.page >= 1000:
        raise SystemExit("--page 必须小于 1000，否则会触发 DATABASE_RESULT_EXCEED_MAX_ROWS")

    rows, last = [], 0
    while True:
        q = ("SELECT %s FROM jobs WHERE owner_id='%s' AND id > %d ORDER BY id LIMIT %d"
             % (COLS, OWNER, last, a.page))
        # 云库 MCP 偶发 500（间歇性），单页失败不应让整轮导出作废
        for attempt in range(5):
            try:
                chunk = dbq.sql(q, "read", as_json=True)
                break
            except Exception as e:
                print("  retry %d: %s" % (attempt + 1, str(e)[:80]))
                time.sleep(3)
        else:
            raise SystemExit("查询连续失败，导出中止：%s" % q[:200])
        if isinstance(chunk, str):
            raise SystemExit("查询失败：" + chunk[:300])
        if not chunk:
            break
        rows.extend(chunk)
        last = chunk[-1]["id"]
        print("  page: +%d (last_id=%d)" % (len(chunk), last))
        if len(chunk) < a.page:
            break

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(rows, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
    print("existing:", len(rows), "->", a.out)


if __name__ == "__main__":
    main()
