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
from pathlib import Path

WS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WS / ".workbuddy" / "tmp"))
import dbq  # noqa: E402

OWNER = "wb:Cndyfv_eOir07ck0FARtAjlvVeet"
COLS = "id, company, position, source_url, salary, location, status, match_score"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", type=int, default=900, help="每页行数，必须 < 1000（云库硬上限）")
    ap.add_argument("--out", default=str(WS / ".workbuddy" / "tmp" / "existing-jobs.json"))
    a = ap.parse_args()
    if a.page >= 1000:
        raise SystemExit("--page 必须小于 1000，否则会触发 DATABASE_RESULT_EXCEED_MAX_ROWS")

    rows, last = [], 0
    while True:
        q = ("SELECT %s FROM jobs WHERE owner_id='%s' AND id > %d ORDER BY id LIMIT %d"
             % (COLS, OWNER, last, a.page))
        chunk = dbq.sql(q, "read", as_json=True)
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
