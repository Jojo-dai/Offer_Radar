#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
领英职位采集（jobs-guest 公开接口直连，不依赖浏览器/登录态）

2026-11-06 重构要点（永久解决"抓不到领英"）：
  1. 门禁判据从"出口 IP 是否 CN"改为"接口是否真的返回岗位卡片"。
     IP 只是环境信号，代理抖动、DNS 分流、IPv6 出口都会让 IP 判定失真，
     但接口能返回 10 条卡片就说明此刻确实抓得到，没必要因为 IP 白白跳过一整天。
  2. 每关键词默认 5 页（start=0/10/20/30/40，实测 start=40 仍有结果），
     单轮 4 词 ≈ 200 条，是旧口径（3 词 × 3 页 = 90 条）的 2.2 倍。
  3. 直连 HTTP + 正则解析，200 条约 2-3 分钟（旧 browse.exe 通道 90 条约 5 分钟）。

2026-11-10 失败词重采队列（防再犯：429 按"整词"丢，每轮最多丢 50 条）：
  4. 某词整轮 0 条（429/网络错误）→ 写入重采队列 <out>/linkedin-retry-queue.json，
     下轮运行自动补采冷却满 30 分钟的失败词（每轮最多补 1 个，总词数 ≤ --max-kws）。
  5. 门禁整体跳过（接口当天不可用）→ 本轮传入词全部入队，恢复后自动补采，不再丢词。

用法：
  python collect-linkedin-guest.py --keywords "SAP BPC,SAP Consultant" [--pages 5] [--out DIR]
退出码：
  0 = 采集完成（至少有一条）
  2 = 接口不可用（302→linkedin.cn / 429 / 空结果），调用方应跳过领英并记录原因
  1 = 其他异常
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
API = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
       "?keywords={kw}&location={loc}&f_TPR={tpr}&start={start}")


def fetch(kw, loc, start, tpr="r604800"):
    url = API.format(kw=urllib.parse.quote(kw), loc=urllib.parse.quote(loc),
                     tpr=tpr, start=start)
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore"), r.geturl()


def _text(m):
    if not m:
        return ""
    s = re.sub(r"<[^>]+>", " ", m.group(1))
    return html.unescape(re.sub(r"\s+", " ", s)).strip()


def parse(h):
    out = []
    for li in re.findall(r"<li>(.*?)</li>", h, re.S):
        t = re.search(r'base-search-card__title">(.*?)</h[34]>', li, re.S)
        c = re.search(r'base-search-card__subtitle">(.*?)</h4>', li, re.S)
        l = re.search(r'job-search-card__location">(.*?)</span>', li, re.S)
        a = re.search(r'href="([^"]*jobs/view/[^"]*)"', li)
        title = _text(t)
        if not title or not a:
            continue
        out.append({
            "title": title,
            "company": _text(c),
            "location": _text(l),
            "link": html.unescape(a.group(1)).split("?")[0],
            "salary": "",
        })
    return out


def probe(keyword, loc):
    """门禁：直接看接口返回。返回 (ok, reason)"""
    try:
        h, final_url = fetch(keyword, loc, 0)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return False, "接口 429 限流（等待 30-60 分钟再试）"
        if e.code == 451:
            return False, "接口 451 区域限制"
        return False, "接口 HTTP %d" % e.code
    except Exception as e:
        return False, "接口不可达：%s" % str(e)[:60]
    if "linkedin.cn" in final_url:
        return False, "被重定向到 linkedin.cn（中国区站点，数据不可用）"
    n = len(parse(h))
    if n == 0:
        return False, "接口返回 0 条岗位卡片"
    return True, "探针词返回 %d 条卡片" % n


# ---------- 失败词重采队列（2026-11-10）----------
RETRY_COOLDOWN = 30 * 60          # 失败词冷却 30 分钟后才允许补采
RETRY_PER_RUN = 1                 # 每轮最多补采 1 个失败词（+1 词 ≈ 50 条 / 40 秒）
QUEUE_KEEP = 20                   # 队列只留最近 20 条，防止无限膨胀


def _queue_path(out):
    return os.path.join(out, "linkedin-retry-queue.json")


def load_queue(out):
    try:
        return json.load(open(_queue_path(out), encoding="utf-8"))
    except Exception:
        return []


def save_queue(out, q):
    q = q[-QUEUE_KEEP:]
    json.dump(q, open(_queue_path(out), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def enqueue_failed(out, kws, reason):
    """把失败词写入队列（去重、刷新时间戳）"""
    if not kws:
        return
    q = [e for e in load_queue(out) if e.get("kw") not in kws]
    ts = time.time()
    for kw in kws:
        q.append({"kw": kw, "ts": ts, "reason": reason})
    save_queue(out, q)


def pick_retry(out, now):
    """取出冷却达标的失败词（每轮最多 RETRY_PER_RUN 个），并从队列移除"""
    q = load_queue(out)
    ready = [e for e in q if now - e.get("ts", 0) >= RETRY_COOLDOWN]
    if not ready:
        return []
    picked = [e["kw"] for e in ready[:RETRY_PER_RUN]]
    save_queue(out, [e for e in q if e["kw"] not in picked])
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", required=True, help="逗号分隔的关键词")
    ap.add_argument("--pages", type=int, default=5)
    ap.add_argument("--out", default=".workbuddy/tmp")
    ap.add_argument("--location", default="Shanghai, China")
    ap.add_argument("--slug-prefix", default="li")
    ap.add_argument("--max-kws", type=int, default=5,
                    help="单轮词数上限（传入词全保留，失败词补采最多 RETRY_PER_RUN 个，超出截断）")
    ap.add_argument("--no-retry-queue", action="store_true",
                    help="禁用失败词队列（测试/探针用）")
    args = ap.parse_args()

    kws_in = [k.strip() for k in args.keywords.split(",") if k.strip()]
    os.makedirs(args.out, exist_ok=True)

    # 合并重采队列：冷却达标的失败词排在最前，优先补采；总词数截到 --max-kws
    retry_picked = []
    if not args.no_retry_queue:
        retry_picked = pick_retry(args.out, time.time())
        if retry_picked:
            print("RETRY-PICK %s（上轮失败词，本轮自动补采）" % ",".join(retry_picked))
    kws = list(dict.fromkeys(retry_picked + kws_in))[:args.max_kws]
    dropped = [k for k in retry_picked if k not in kws]
    if dropped:
        # 没轮到的失败词放回队列，下轮再试
        enqueue_failed(args.out, dropped, "本轮词数已满，顺延")
        print("RETRY-DEFER %s（本轮词数已满，已顺延）" % ",".join(dropped))

    # 门禁：用前两个词做探针，避免"某个词本就无结果"被误判成接口不可用
    ok, reason = False, "未探测"
    for probe_kw in kws[:2]:
        ok, reason = probe(probe_kw, args.location)
        print("GATE %s [%s] %s" % ("PASS" if ok else "RETRY", probe_kw, reason))
        if ok:
            break
    if not ok:
        # 门禁失败 = 本轮一个词都没采到 → 全部入队，接口恢复后自动补采
        if not args.no_retry_queue:
            enqueue_failed(args.out, kws, "门禁跳过：%s" % reason)
        print("SKIP linkedin: %s%s" % (reason, "" if args.no_retry_queue else "（%d 个词已入重采队列）" % len(kws)))
        return 2

    total = 0
    failed_kws = []
    for i, kw in enumerate(kws, 1):
        slug = "%s-%d" % (args.slug_prefix, i)
        got = 0
        throttled = False   # True = 被 429/网络错误中断（而非正常翻完没结果）
        for page in range(args.pages):
            start = page * 10
            # 429 自适应：先冷却 45-75 秒重试一次，仍 429 才放弃该词
            h = None
            for attempt in (1, 2):
                try:
                    h, _ = fetch(kw, args.location, start)
                    break
                except urllib.error.HTTPError as e:
                    if e.code == 429 and attempt == 1:
                        cool = 45 + (os.getpid() % 30)
                        print("  THROTTLE kw=%s start=%d 429，冷却 %ds 后重试" % (kw, start, cool))
                        time.sleep(cool)
                        continue
                    print("  ERR kw=%s start=%d %s" % (kw, start, str(e)[:60]))
                    throttled = True
                    break
                except Exception as e:
                    print("  ERR kw=%s start=%d %s" % (kw, start, str(e)[:60]))
                    throttled = True
                    break
            if not h:
                break
            items = parse(h)
            path = os.path.join(args.out, "li-page-%s-%d.json" % (slug, start))
            json.dump(items, open(path, "w", encoding="utf-8"), ensure_ascii=False)
            print("  kw=%s start=%d items=%d" % (kw, start, len(items)))
            got += len(items)
            if len(items) < 10:
                break
            time.sleep(3 + (os.getpid() + page) % 3)   # 3-5 秒抖动，降低被限流概率
        total += got
        print("KW=%s total=%d" % (kw, got))
        if got == 0 and throttled:
            failed_kws.append(kw)
        time.sleep(4 + (os.getpid() % 3))

    if failed_kws and not args.no_retry_queue:
        # 只把"被限流/网络错误中断"的词入队；正常翻完没结果的词不入队（避免死循环补采空词）
        enqueue_failed(args.out, failed_kws, "整词 0 条（429/网络错误）")
        print("RETRY-ENQUEUE %s（失败词已入队，下轮自动补采）" % ",".join(failed_kws))

    print("ALL DONE total=%d keywords=%d pages=%d" % (total, len(kws), args.pages))
    return 0 if total else 2


if __name__ == "__main__":
    sys.exit(main())
