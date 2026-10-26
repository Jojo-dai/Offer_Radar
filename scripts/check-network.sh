#!/usr/bin/env bash
# ============================================================
# 领英可达性自检
#   硬断言（全过才允许跑领英）：
#     1) 出口 IP 地理判定不是 CN
#     2) linkedin.com/jobs/search 返回 200（不是 302 → linkedin.cn）
#   辅助判定（仅提示，不参与退出码）：
#     3) 出口 IP 与本机直连 IP 的关系（TUN 全局模式下两者相同是正常现象）
#
# 用法：bash scripts/check-network.sh [socks|http] [host:port]
# 退出码：0 = 允许跑领英；1 = 必须跳过
# ============================================================
set -u

MODE="${1:-auto}"
PROXY="${2:-}"
FAIL=0

say() { printf '%s\n' "$*"; }
ok()  { say "  ✅ $*"; }
bad() { FAIL=$((FAIL+1)); say "  ❌ $*"; }

# ---- 选择代理（只影响本次 curl，不改本机配置） ----
CURL_PROXY=()
if [ -n "$PROXY" ]; then
  case "$MODE" in
    socks) CURL_PROXY=(--socks5-hostname "$PROXY") ;;
    *)     CURL_PROXY=(-x "http://$PROXY") ;;
  esac
  say "使用代理：$MODE $PROXY"
else
  for p in 127.0.0.1:7897 127.0.0.1:7890 127.0.0.1:10809 127.0.0.1:8080; do
    if (exec 3<>"/dev/tcp/127.0.0.1/${p##*:}") 2>/dev/null; then
      CURL_PROXY=(-x "http://$p"); say "自动探测到本地代理：$p"; break
    fi
  done
  [ ${#CURL_PROXY[@]} -eq 0 ] && say "未探测到本地代理（TUN 模式下无需指定，直接测试）"
fi

# 统一绕过 shell 环境里的 http(s)_proxy，避免测试目标被污染
BASE=(curl -s --noproxy '*' --max-time 20 "${CURL_PROXY[@]}")

say ""
say "=== 硬断言 1：出口 IP 的地理判定不能是 CN ==="
TRACE=$("${BASE[@]}" https://www.cloudflare.com/cdn-cgi/trace 2>/dev/null || true)
IP=$(printf '%s\n' "$TRACE" | awk -F= '/^ip=/{print $2}')
LOC=$(printf '%s\n' "$TRACE" | awk -F= '/^loc=/{print $2}')
COLO=$(printf '%s\n' "$TRACE" | awk -F= '/^colo=/{print $2}')
say "  ip=${IP:-读取失败}  loc=${LOC:-未知}  colo=${COLO:-未知}"
if [ -z "${IP:-}" ]; then
  bad "拿不到出口 IP：代理未接管 / 不通"
elif [ "$LOC" = "CN" ]; then
  bad "出口被判为中国大陆（loc=CN）→ 领英会 302 到 linkedin.cn"
else
  ok "出口地区 ${LOC}（非 CN）"
fi

say ""
say "=== 硬断言 2：领英搜索页必须返回 200 ==="
RES=$(curl -s --noproxy '*' --max-time 25 "${CURL_PROXY[@]}" \
      -o /dev/null -w '%{http_code} %{redirect_url}' \
      'https://www.linkedin.com/jobs/search/?keywords=AI%20Product%20Manager' 2>/dev/null || true)
CODE=$(printf '%s' "$RES" | awk '{print $1}')
REDIR=$(printf '%s' "$RES" | cut -d' ' -f2-)
say "  HTTP=$CODE  redirect=${REDIR:-无}"
case "$CODE" in
  200) ok "领英搜索页 200" ;;
  302) if printf '%s' "$REDIR" | grep -q 'linkedin\.cn'; then
         bad "302 → linkedin.cn：出口被判 CN，或 linkedin.com 被分流走直连"
       else
         bad "302 → ${REDIR}（非预期跳转，需人工确认）"
       fi ;;
  451) bad "451：区域限制（IP 被判中国大陆）" ;;
  999) bad "999：领英风控（请求特征被拦）" ;;
  000) bad "无响应：代理不通或超时" ;;
  *)   bad "返回 ${CODE}，非 200" ;;
esac

say ""
say "=== 辅助判定 3：出口 IP 与本机直连 IP 的关系（仅提示） ==="
DIRECT_IP=$(curl -s --noproxy '*' --max-time 15 https://ipinfo.io/ip 2>/dev/null || true)
say "  直连 IP=${DIRECT_IP:-读取失败}  代理出口 IP=${IP:-读取失败}"
if [ -z "${DIRECT_IP:-}" ]; then
  say "  ℹ️ 直连 IP 读取失败（本机可能被墙），跳过该判定"
elif [ "${DIRECT_IP}" = "${IP:-}" ]; then
  say "  ℹ️ 两者相同：TUN 全局模式下属正常（所有流量都进隧道）；"
  say "     但若是「系统代理模式」且仍相同，则说明流量漏回直连 —— 以硬断言 1、2 为准"
else
  say "  ℹ️ 两者不同：隧道已生效"
fi

say ""
say "================ 结论 ================"
if [ "$FAIL" -eq 0 ]; then
  say "✅ 硬断言全部通过：允许执行领英采集"
  exit 0
else
  say "⛔ 有 ${FAIL} 项硬断言未通过：本轮必须跳过领英采集并记录失败原因；"
  say "   严禁改成直连继续抓取（linkedin.cn 是中国区内容，数据不可用）。"
  say ""
  say "修复顺序："
  say "  1) 开启 TUN 模式，或确认系统代理真正接管流量"
  say "  2) Fake-IP 必须与 TUN 配对；只开 Fake-IP 不开 TUN 会全部漏回直连"
  say "  3) 分流规则里 linkedin.com 不能走直连（切全局或加白名单）"
  say "  4) 换节点：优先美国 IPv4 出口，避开被判 CN 的亚太 IPv6 段"
  exit 1
fi
