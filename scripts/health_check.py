#!/usr/bin/env python3
"""Offer Radar 一键体检：外部依赖 / 本地资源 / 前端测试 / 上传档案库。

全部路径相对仓库根目录，可在任意机器、CI 中直接运行：
    python scripts/health_check.py
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PAGE = REPO / "app/index.html"
VENDOR = REPO / "app/vendor"
ARCHIVE = REPO / "uploads"
NODE = os.environ.get("NODE") or shutil.which("node") or "node"

BAD_URLS = [
    "cdnjs.cloudflare.com",
    "cdn.jsdelivr.net/npm/@tencent-ai",
    "cdn.jsdelivr.net/npm/mammoth",
    "cdn.jsdelivr.net/npm/pdfjs-dist",
    "cdn.jsdelivr.net/npm/tesseract.js",
    "cdn.jsdelivr.net/npm/@tesseract.js-data",
]
REQUIRED = [
    "workbuddy-cloud-sdk.global.js",
    "mammoth.browser.min.js",
    "pdf.min.js",
    "pdf.worker.min.js",
    "tesseract.min.js",
    "worker.min.js",
    "core/tesseract-core-lstm.wasm.js",
    "tessdata/chi_sim.traineddata.gz",
]

failures = []


def check(name, ok, detail=""):
    print(f"{'[PASS]' if ok else '[FAIL]'} {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def run(cmd):
    p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout + p.stderr).strip()


# 1. 页面不得在运行时依赖公网脚本
text = PAGE.read_text(encoding="utf-8")
hit = [u for u in BAD_URLS if u in text]
check("app/index.html 无外部脚本依赖", not hit, "命中：" + ", ".join(hit) if hit else "")
check("app/index.html 引用本地 SDK", '<script src="./vendor/workbuddy-cloud-sdk.global.js"></script>' in text)
check("app/index.html SDK 失败提示", "云 SDK 加载失败：应用资源不完整" in text)
check("app/index.html 账号隔离助手", "const MY_OWNER" in text and ".eq('owner_id', MY_OWNER())" in text)

# 2. 本地静态资源齐全且语法有效
for rel in REQUIRED:
    p = VENDOR / rel
    check(f"vendor/{rel}", p.is_file() and p.stat().st_size > 100, f"{p.stat().st_size if p.is_file() else 0} bytes")
for js in VENDOR.rglob("*.js"):
    code, out = run([NODE, "--check", str(js)])
    check(f"JS 语法 {js.relative_to(VENDOR)}", code == 0, out[:160])

# 3. 项目自带测试
code, out = run([NODE, "scripts/smoke-frontend.js", "app/index.html"])
check("前端冒烟测试", code == 0, out.splitlines()[-1] if out else "")
code, out = run([NODE, "scripts/test-decisions.js", "app/index.html"])
check("决策逻辑测试 9/9", code == 0 and "通过 9 / 9" in out, out.splitlines()[-1] if out else "")

# 4. 本地上传档案库（目录被 .gitignore 忽略，不进仓库）
code, out = run([sys.executable, "scripts/archive_upload.py", "verify"])
check("上传档案库完整性", code == 0, out.strip())
manifest = ARCHIVE / "manifest.json"
if manifest.is_file():
    m = json.loads(manifest.read_text(encoding="utf-8"))
    bad = [i["id"] for i in m["items"] if not i.get("owner_id") or not i.get("stored_path", "").startswith("by-account/")]
    check("档案库账号隔离与路径", not bad, "异常：" + ", ".join(bad) if bad else f"{len(m['items'])} 条")

print("\n" + ("全部体检通过" if not failures else f"体检失败 {len(failures)} 项：" + "；".join(failures)))
raise SystemExit(1 if failures else 0)
