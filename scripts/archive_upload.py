#!/usr/bin/env python3
"""投递助手 · 上传文件本地档案库

原则：
1. 只复制、不移动、不删改源文件——用户原件原地不动。
2. 入库文件立即置只读；重复内容（sha256 相同）直接跳过，绝不覆盖。
3. 每条记录绑定 owner_id，物理目录按账号分隔，manifest 与展示页都按账号过滤。
4. 展示页把 manifest 内联进 HTML，双击即可看，不依赖 fetch/CORS。

用法：
  python archive_upload.py add <文件> --owner wb:xxx [--owner-name 名字] [--kind 简历原件] [--note 说明]
  python archive_upload.py list [--owner wb:xxx]
  python archive_upload.py verify
  python archive_upload.py serve [--port 8899]
"""
import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "uploads"
MANIFEST = ARCHIVE / "manifest.json"
INDEX = ARCHIVE / "index.html"


def now_iso():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds")


def sha256_of(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_owner(owner_id: str):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", owner_id) or "unknown"


def load_manifest():
    if not MANIFEST.exists():
        return {"version": 1, "created_at": now_iso(), "items": []}
    with MANIFEST.open(encoding="utf-8") as f:
        return json.load(f)


def save_manifest(m):
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
    render_index(m)


def make_readonly(path: Path):
    try:
        os.chmod(path, stat.S_IREAD)
    except Exception:
        pass
    if os.name == "nt":
        try:
            subprocess.run(["attrib", "+R", str(path)], check=False, capture_output=True)
        except Exception:
            pass


def cmd_add(args):
    src = Path(args.file).resolve()
    if not src.is_file():
        raise SystemExit(f"源文件不存在：{src}")
    digest = sha256_of(src)
    m = load_manifest()

    for item in m["items"]:
        if item["sha256"] == digest and item["owner_id"] == args.owner:
            print(f"已归档（内容相同），跳过：{src.name}")
            print(f"  原档案：{item['stored_path']}")
            return

    folder = ARCHIVE / "by-account" / safe_owner(args.owner)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{digest[:10]}_{src.name}"
    target = folder / name
    seq = 1
    while target.exists():
        target = folder / f"{digest[:10]}_{seq}_{src.name}"
        seq += 1

    shutil.copy2(src, target)  # 只复制，源文件保持原样
    make_readonly(target)

    m["items"].append({
        "id": dt.datetime.now().strftime("%Y%m%d%H%M%S") + "-" + digest[:8],
        "owner_id": args.owner,
        "owner_name": args.owner_name or "",
        "original_name": src.name,
        "stored_path": str(target.relative_to(ARCHIVE)).replace("\\", "/"),
        "sha256": digest,
        "size": target.stat().st_size,
        "archived_at": now_iso(),
        "source_path": str(src),
        "kind": args.kind or "上传文件",
        "note": args.note or "",
        "readonly": True,
    })
    save_manifest(m)
    print(f"已归档：{src.name} -> {target.relative_to(ARCHIVE)}")
    print(f"  sha256={digest[:16]}…  只读=是  源文件未改动")


def cmd_list(args):
    m = load_manifest()
    items = [i for i in m["items"] if not args.owner or i["owner_id"] == args.owner]
    if not items:
        print("档案库为空（或该账号下没有档案）")
        return
    for i in items:
        print(f"[{i['id']}] {i['kind']} | {i['original_name']} | {i['size']}B")
        print(f"    owner={i['owner_id']}  {i['archived_at']}")
        print(f"    path={i['stored_path']}")


def cmd_verify(args=None):
    m = load_manifest()
    bad = 0
    for i in m["items"]:
        p = ARCHIVE / i["stored_path"]
        if not p.exists():
            print(f"缺失：{i['stored_path']}")
            bad += 1
            continue
        actual = sha256_of(p)
        if actual != i["sha256"]:
            print(f"被改动：{i['stored_path']}")
            bad += 1
        elif os.name == "nt":
            raw = subprocess.run(["attrib", str(p)], capture_output=True).stdout or b""
            out = raw.decode("mbcs", errors="ignore").upper()
            cut = out.find(":")
            flags = out[:cut] if cut > 0 else out[:24]
            if "R" not in flags:
                print(f"只读标记丢失：{i['stored_path']}")
                bad += 1
    print(f"校验完成：{len(m['items'])} 条档案，异常 {bad} 条")
    if bad:
        raise SystemExit(1)


def cmd_serve(args):
    os.chdir(ARCHIVE)
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    server = ThreadingHTTPServer(("127.0.0.1", args.port), SimpleHTTPRequestHandler)
    print(f"本地档案库：http://127.0.0.1:{args.port}/  （Ctrl+C 停止）")
    server.serve_forever()


def render_index(m):
    owners = sorted({i["owner_id"] for i in m["items"]})
    rows = []
    for i in sorted(m["items"], key=lambda x: x["archived_at"], reverse=True):
        rows.append({
            "id": i["id"], "owner": i["owner_id"], "ownerName": i["owner_name"],
            "name": i["original_name"], "kind": i["kind"], "size": i["size"],
            "at": i["archived_at"], "path": i["stored_path"],
            "sha": i["sha256"][:16], "source": i["source_path"], "note": i["note"],
        })
    payload = json.dumps({"owners": owners, "rows": rows}, ensure_ascii=False)
    doc = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>上传档案库 · 投递助手</title>
<style>
:root{--bg:#f5f6f8;--card:#fff;--line:#e5e7eb;--txt:#1f2329;--sub:#6b7280;--brand:#2f6bff;--ok:#16a34a}
*{box-sizing:border-box;margin:0;padding:0}body{font:14px/1.6 "Microsoft YaHei",system-ui;background:var(--bg);color:var(--txt)}
.wrap{max-width:1080px;margin:0 auto;padding:24px 20px}h1{font-size:22px;margin-bottom:4px}
.sub{color:var(--sub);margin-bottom:18px}.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
select,input{border:1px solid var(--line);border-radius:8px;padding:7px 10px;background:#fff;font-size:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:10px}
.head{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center}
.name{font-weight:700;font-size:15px}.tag{display:inline-block;background:#eaf0ff;color:var(--brand);border-radius:6px;padding:1px 8px;font-size:12px;margin-right:6px}
.ok{background:#e7f7ec;color:var(--ok)}.meta{color:var(--sub);font-size:12.5px;margin-top:6px;word-break:break-all}
a{color:var(--brand);text-decoration:none}a:hover{text-decoration:underline}
.empty{color:var(--sub);text-align:center;padding:40px 0}code{background:#f1f3f5;border-radius:4px;padding:1px 5px;font-size:12px}
</style></head><body><div class="wrap">
<h1>📁 上传档案库</h1>
<p class="sub">原件只读归档，按账号隔离。所有文件仅存本机，不上传云端；显示的是档案副本，原始文件保持原位。</p>
<div class="bar"><label>账号 <select id="owner"><option value="">全部账号</option></select></label>
<label>搜索 <input id="q" placeholder="文件名 / 用途 / 备注"></label><span id="cnt" class="sub"></span></div>
<div id="list"></div></div>
<script>
const DATA = __DATA__;
const el = s => document.querySelector(s);
const esc = s => String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
DATA.owners.forEach(o=>{const op=document.createElement('option');op.value=o;op.textContent=o;el('#owner').appendChild(op)});
function render(){
  const owner=el('#owner').value, q=el('#q').value.trim().toLowerCase();
  const rows=DATA.rows.filter(r=>(!owner||r.owner===owner)&&(!q||[r.name,r.kind,r.note,r.source].join(' ').toLowerCase().includes(q)));
  el('#cnt').textContent=`共 ${rows.length} 份档案`;
  el('#list').innerHTML = rows.length ? rows.map(r=>`<div class="card">
    <div class="head"><div class="name">${esc(r.name)}</div>
      <a href="${encodeURI(r.path)}" target="_blank">打开原件 ↗</a></div>
    <div><span class="tag">${esc(r.kind)}</span><span class="tag ok">只读 · 不可覆盖</span>
      <span class="tag">${esc(r.ownerName||r.owner)}</span></div>
    <div class="meta">归档：${esc(r.at)} · ${(r.size/1024).toFixed(1)} KB · sha256:${esc(r.sha)}…</div>
    <div class="meta">来源：${esc(r.source)}${r.note?' · 备注：'+esc(r.note):''}</div>
  </div>`).join('') : '<div class="empty">该筛选条件下暂无档案</div>';
}
el('#owner').onchange=render;el('#q').oninput=render;render();
</script></body></html>"""
    INDEX.write_text(doc.replace("__DATA__", payload), encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description="上传文件本地档案库")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add")
    a.add_argument("file")
    a.add_argument("--owner", required=True)
    a.add_argument("--owner-name", default="")
    a.add_argument("--kind", default="上传文件")
    a.add_argument("--note", default="")
    a.set_defaults(func=cmd_add)

    l = sub.add_parser("list")
    l.add_argument("--owner")
    l.set_defaults(func=cmd_list)

    v = sub.add_parser("verify")
    v.set_defaults(func=cmd_verify)

    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8899)
    s.set_defaults(func=cmd_serve)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
