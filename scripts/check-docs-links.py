#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查 Markdown 里的相对链接与图片是否真实存在。

为什么需要它：这个仓库的文档是产品的说明书，链接断掉比代码报错更隐蔽——
读者点进去 404 只会默默关掉页面。CI 里跑一遍，断链就是红叉。

检查范围：仓库根与 docs/ 下所有 .md（跳过 .git / node_modules / 外部 URL）。
只校验「目标文件是否存在」，不校验锚点（中文锚点在不同渲染器下规则不一致，容易误报）。

用法：
    python scripts/check-docs-links.py            # 在仓库根执行
    python scripts/check-docs-links.py --quiet    # 只输出问题
退出码：0 = 全部可达；1 = 存在断链或空目标
"""
import os
import re
import sys

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "assets"}
LINK_RE = re.compile(r"""!?\[[^\]]*\]\(\s*([^)\s]+)(?:\s+"[^"]*")?\s*\)""")
CODE_FENCE_RE = re.compile(r"```.*?```", re.S)
INLINE_CODE_RE = re.compile(r"`[^`]*`")


def iter_markdown(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.lower().endswith(".md"):
                yield os.path.join(dirpath, name)


def strip_code(text):
    """代码块/行内代码里的 []() 不是链接，先剔掉避免误报。"""
    text = CODE_FENCE_RE.sub("", text)
    return INLINE_CODE_RE.sub("", text)


def check(root):
    problems = []
    total = 0
    for path in sorted(iter_markdown(root)):
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        text = strip_code(raw)
        base = os.path.dirname(path)
        for line_no, line in enumerate(text.splitlines(), 1):
            for target in LINK_RE.findall(line):
                target = target.strip()
                if not target:
                    problems.append((path, line_no, target, "空链接目标"))
                    continue
                if target.startswith(("http://", "https://", "mailto:", "tel:", "#")):
                    continue
                total += 1
                clean = target.split("#", 1)[0].split("?", 1)[0]
                if not clean:
                    continue
                resolved = os.path.normpath(os.path.join(base, clean))
                if not os.path.exists(resolved):
                    problems.append((path, line_no, target, "目标不存在"))
    return total, problems


def main():
    quiet = "--quiet" in sys.argv
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    total, problems = check(root)
    if problems:
        print("发现 %d 处断链（共检查 %d 条相对链接）：" % (len(problems), total))
        for path, line_no, target, reason in problems:
            rel = os.path.relpath(path, root)
            print("  %s:%d  %s  -> %s" % (rel, line_no, reason, target))
        return 1
    if not quiet:
        print("文档链接检查通过：%d 条相对链接全部可达。" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
