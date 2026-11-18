#!/usr/bin/env python3
"""给投递助手前端所有云库调用补上显式 owner_id 条件（纵深防御）。

设计：
- insert：显式写入 owner_id: MY_OWNER()
- select/update/delete：链式末尾追加 .eq('owner_id', MY_OWNER())
- 已有 owner_id 条件的语句跳过，避免重复
- 只在语句结尾的分号处切分，跟踪引号与括号深度，避免误伤字符串里的分号
"""
import re
import sys


def scope(text: str) -> str:
    nl = "\r\n" if "\r\n" in text[:2000] else "\n"
    helper = "const MY_OWNER = () => (session && session.user && session.user.id) || '';" + nl
    if "const MY_OWNER" not in text:
        anchor = "let session = null, modelId = null"
        pos = text.find(anchor)
        if pos < 0:
            raise SystemExit("找不到 session 声明锚点，终止")
        line_end = text.find(nl, pos) + len(nl)
        text = text[:line_end] + helper + text[line_end:]

    out = []
    i = 0
    changed = 0
    while True:
        start = text.find("cloud.database.from(", i)
        if start < 0:
            out.append(text[i:])
            break
        out.append(text[i:start])

        j = start
        depth = 0
        quote = None
        esc = False
        while j < len(text):
            c = text[j]
            if quote:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == quote:
                    quote = None
            else:
                if c in "'\"`":
                    quote = c
                elif c in "([{":
                    depth += 1
                elif c in ")]}":
                    depth -= 1
                elif c == ";" and depth <= 0:
                    break
            j += 1

        stmt = text[start:j]
        if ".eq('owner_id'" not in stmt:
            if ".insert(" in stmt:
                m = re.search(r"\.insert\(\s*\{", stmt)
                if not m:
                    raise SystemExit("找到 insert 但没有对象字面量，终止: " + stmt[:120])
                pos = m.end()
                stmt = stmt[:pos] + " owner_id: MY_OWNER()," + stmt[pos:]
                changed += 1
            else:
                stripped = stmt.rstrip()
                term = None
                for name in (".select()", ".maybeSingle()", ".single()"):
                    if stripped.endswith(name):
                        term = name
                        break
                if term:
                    pos = len(stmt) - len(stmt.lstrip()) + len(stmt.rstrip()) - len(term)
                    # 直接按 rfind 定位终端方法，避免缩进计算误差
                    pos = stmt.rfind(term)
                    stmt = stmt[:pos] + ".eq('owner_id', MY_OWNER())" + stmt[pos:]
                else:
                    stmt = stmt + ".eq('owner_id', MY_OWNER())"
                changed += 1
        out.append(stmt)
        i = j

    return "".join(out), changed


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8", newline="") as f:
        result, n = scope(f.read())
    with open(dst, "w", encoding="utf-8", newline="") as f:
        f.write(result)
    print(f"scoped {n} database calls -> {dst}")
