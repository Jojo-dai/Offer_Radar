#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云库只读取数层（供 audit-decisions.py 等审计脚本使用）

为什么需要这一层：
审计脚本原来直接 `import dbq`，那是开发机 `.workbuddy/tmp/` 下的临时模块，
不在仓库里 —— 别人 clone 之后脚本必然 `ModuleNotFoundError`，等于这份审计能力
无法交付。这里把「怎么连库」和「连哪个用户的库」都变成显式配置。

两种后端，按优先级自动选择：

  A. 标准 PostgreSQL（推荐给自建库 / 迁到 Supabase 的用户）
     配置：export DATABASE_URL='postgresql://user:pass@host:5432/postgres'
     依赖：pip install psycopg2-binary
     说明：用只读账号即可，本层只执行 SELECT。

  B. WorkBuddy 云库 MCP（项目原始运行环境）
     配置：export WB_MCP_CONFIG='<MCP servers JSON>'   # 含 url 与 headers
           export WB_APP_ID='wbapp_xxx'                # 你的应用 ID
     说明：调用 workbuddy_cloudservice_db_exec_sql，mode 固定为 read。

两者都没配置时，抛出 ConfigError 并给出可直接照抄的配置示例，
而不是抛一个看不出原因的 ImportError。

owner_id 不在这里读 —— 由调用方通过参数或 OWNER_ID 环境变量传入，
避免把某个具体账号写进公共代码。
"""
import json
import os
import urllib.request


class ConfigError(RuntimeError):
    """配置缺失或不可用。消息面向使用者，应可直接照抄修复。"""


def backend():
    """返回当前生效的后端名：'postgres' / 'mcp'；都没有则抛 ConfigError。"""
    if os.environ.get("DATABASE_URL", "").strip():
        return "postgres"
    if os.environ.get("WB_MCP_CONFIG", "").strip():
        return "mcp"
    raise ConfigError(
        "没有可用的数据库连接配置。二选一：\n"
        "  A) 标准 PostgreSQL（推荐）\n"
        "     export DATABASE_URL='postgresql://user:pass@host:5432/postgres'\n"
        "     pip install psycopg2-binary\n"
        "  B) WorkBuddy 云库 MCP\n"
        "     export WB_MCP_CONFIG='<mcpServers 的 JSON>'\n"
        "     export WB_APP_ID='wbapp_xxx'\n"
        "详见 docs/12-decisions-patch.md 第 3 节「配置说明」。"
    )


def _rows_postgres(sql):
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        raise ConfigError(
            "检测到 DATABASE_URL 但缺少驱动。请先执行：\n"
            "  pip install psycopg2-binary\n"
            "（或用纯 Python 的 pg8000 并自行替换本函数的连接实现）"
        )
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _rows_mcp(sql):
    app = (os.environ.get("WB_APP_ID") or os.environ.get("APPLICATION_ID") or "").strip()
    if not app:
        raise ConfigError("使用 MCP 后端时必须设置 WB_APP_ID（你的 applicationId，形如 wbapp_xxx）。")
    try:
        cfg = json.loads(os.environ["WB_MCP_CONFIG"])
        srv = cfg["mcpServers"]["genie-baas"]
        url, hdr = srv["url"], dict(srv.get("headers") or {})
    except (ValueError, KeyError, TypeError) as e:
        raise ConfigError("WB_MCP_CONFIG 不是预期的 mcpServers JSON 结构：%s" % e)

    hdr["Content-Type"] = "application/json"
    hdr["Accept"] = "application/json, text/event-stream"
    body = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "workbuddy_cloudservice_db_exec_sql",
                   "arguments": {"applicationId": app, "mode": "read", "sql": sql}},
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=hdr)
    raw = urllib.request.urlopen(req, timeout=120).read().decode("utf-8", "ignore")

    # MCP 可能以 SSE 帧返回，取最后一个 data: 行
    lines = [ln for ln in raw.splitlines() if ln.startswith("data: ")]
    if lines:
        raw = lines[-1][6:]
    d = json.loads(raw)
    if "error" in d:
        raise ConfigError("MCP 调用失败：" + json.dumps(d["error"], ensure_ascii=False)[:500])
    res = d.get("result") or {}
    txt = "".join(c.get("text", "") for c in (res.get("content") or []) if c.get("type") == "text")
    if res.get("isError"):
        raise ConfigError("查询报错：" + txt[:500])
    try:
        return json.loads(txt)
    except ValueError:
        raise ConfigError("返回内容不是 JSON 数组：" + txt[:300])


def fetch_rows(sql):
    """执行只读 SQL，返回 list[dict]。"""
    b = backend()
    rows = _rows_postgres(sql) if b == "postgres" else _rows_mcp(sql)
    if isinstance(rows, dict):  # 某些实现返回 {rows:[...]}
        rows = rows.get("rows") or rows.get("data") or []
    return rows


def resolve_owner(cli_value=None):
    """按 命令行 > OWNER_ID 环境变量 的顺序取 owner_id，都没有则报错。"""
    owner = (cli_value or os.environ.get("OWNER_ID") or "").strip()
    if not owner:
        raise ConfigError(
            "缺少 owner_id。它是你库中数据的归属标识（jobs.owner_id 的值）。\n"
            "  取法：SELECT DISTINCT owner_id FROM jobs LIMIT 5;\n"
            "  用法：export OWNER_ID='wb:xxxx'  或  --owner 'wb:xxxx'"
        )
    return owner
