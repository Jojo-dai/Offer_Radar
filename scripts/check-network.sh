#!/usr/bin/env bash
# ============================================================
# 领英可达性自检（2026-11-06 重构：以接口实测为准，不再用 IP 国家做硬断言）
#
# 为什么改：旧的硬断言是「出口 IP 地理判定必须不是 CN」。
#   实测中代理抖动 / DNS 分流 / IPv6 出口都会让 IP 判定失真——
#   11-06 两轮采集都因 IP 判为 CN 直接放弃领英，结果当天领英 0 条，
#   而当时 jobs-guest 接口其实是可用的。
#
# 现在的判据（唯一硬断言）：
#   直接请求 jobs-guest 接口，能解析出 ≥1 条岗位卡片 → 允许采集。
#   IP、DNS、跳转只作为辅助信息打印，不影响结论。
#
# 用法：bash scripts/check-network.sh
# 退出码：0 = 允许跑领英；1 = 必须跳过（接口 302→linkedin.cn / 429 / 451 / 0 条）
# ============================================================
set -u

UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
PROBE_URL='https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=SAP%20BPC&location=Shanghai%2C%20China&f_TPR=r604800&start=0'

say() { printf '%s\n' "$*"; }

say ""
say "=== 辅助信息：出口 IP（仅提示，不再作为硬断言） ==="
TRACE=$(curl -s --max-time 15 https://www.cloudflare.com/cdn-cgi/trace 2>/dev/null || true)
IP=$(printf '%s\n' "$TRACE" | awk -F= '/^ip=/{print $2}')
LOC=$(printf '%s\n' "$TRACE" | awk -F= '/^loc=/{print $2}')
say "  ip=${IP:-读取失败}  loc=${LOC:-未知}"
if [ "${LOC:-}" = "CN" ]; then
  say "  ℹ️ 出口判为中国大陆：通常会被 302 到 linkedin.cn，但以接口实测为准"
fi

say ""
say "=== 硬断言：jobs-guest 接口必须返回岗位卡片 ==="
BODY=$(curl -s --max-time 30 -A "$UA" -w '\n__STATUS__%{http_code}__URL__%{url_effective}' "$PROBE_URL" 2>/dev/null || true)
STATUS=$(printf '%s' "$BODY" | sed -n 's/.*__STATUS__\([0-9]*\)__URL__.*/\1/p')
FINAL=$(printf '%s' "$BODY" | sed -n 's/.*__STATUS__[0-9]*__URL__//p')
CARDS=$(printf '%s' "$BODY" | grep -o 'base-search-card__title' | wc -l | tr -d ' ')
say "  HTTP=${STATUS:-无}  卡片=${CARDS:-0}"
say "  最终地址=${FINAL:-无}"

if printf '%s' "${FINAL:-}" | grep -q 'linkedin\.cn'; then
  say ""
  say "⛔ 接口被重定向到 linkedin.cn（中国区站点）：本轮跳过领英"
  say "   修复：开启 TUN 全局 / 确认 linkedin.com 不走直连 / 换美国节点"
  exit 1
fi

case "${STATUS:-}" in
  200)
    if [ "${CARDS:-0}" -gt 0 ]; then
      say ""
      say "================ 结论 ================"
      say "✅ 接口可用（返回 ${CARDS} 条卡片）：允许执行领英采集"
      exit 0
    fi
    say ""
    say "⛔ 接口 200 但 0 条卡片：关键词或地区无结果，或页面结构变化 → 跳过并记录"
    exit 1
    ;;
  429) say ""; say "⛔ 429 限流：等 30-60 分钟再试，期间不要采集（重试只会加重限流）"; exit 1 ;;
  451) say ""; say "⛔ 451 区域限制：换节点后重试"; exit 1 ;;
  000) say ""; say "⛔ 无响应：网络不通"; exit 1 ;;
  *)   say ""; say "⛔ 返回 ${STATUS:-未知}：跳过领英并记录原因"; exit 1 ;;
esac
