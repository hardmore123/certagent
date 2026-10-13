#!/usr/bin/env bash
# certagent 开机依赖就绪探测（ExecStartPre）
#
# CertAgent 断电重启保护：它的依赖比 certverify 简单——
#   1) 网络/路由就绪
#   2) 内网 LLM 网关可达（.env 里的 LLM_BASE_URL，默认 inner-apisix.hisense.com）
# 每个依赖都有上限；超时只告警不阻塞启动（LLM 网关不在也不影响 Web 服务本身启动）。
# 始终 exit 0：依赖缺失 = 可用但降级，绝不能把启动判失败导致 StartLimit 循环。

set -u

PROJ=/home/hisense/pro/Gitlab/CertAgent
LOG=/tmp/certagent_ready.log

log() { printf '%s %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG"; }

# 1. 等路由/网络就绪（最多 30s）
for i in $(seq 1 15); do
    if ip route get 10.18.87.51 >/dev/null 2>&1 || ping -c1 -W1 10.18.87.51 >/dev/null 2>&1; then
        log "[ok] 网络/路由就绪"; break
    fi
    [ "$i" = 15 ] && log "[warn] 网络/路由 30s 未就绪（继续启动）"
    sleep 2
done

# 2. 等内网 LLM 网关可达（最多 60s；不可达则 AI 建议降级，Web 本体不影响）
LLM_BASE=""
if [ -f "$PROJ/.env" ]; then
    # .env 可能是 Windows CRLF，行尾的 \r 必须剥掉，否则主机名带 \r 导致 DNS 解析失败
    LLM_BASE=$(grep -E '^LLM_BASE_URL=' "$PROJ/.env" 2>/dev/null | head -1 \
        | sed 's/^LLM_BASE_URL=//' | tr -d '"\r' | xargs)
fi
if [ -n "$LLM_BASE" ]; then
    HOST="${LLM_BASE#*://}"; HOST="${HOST%%/*}"
    # 取主机:端口；无显式端口则 http=80 / https=443
    H="${HOST%%:*}"; P="${HOST##*:}"
    case "${LLM_BASE%%:*}" in
        https) [ "$P" = "$H" ] && PORT=443 || PORT="$P" ;;
        *)     [ "$P" = "$H" ] && PORT=80  || PORT="$P" ;;
    esac
    for i in $(seq 1 60); do
        bash -c "exec 3<>/dev/tcp/$H/$PORT" >/dev/null 2>&1 && { log "LLM 网关 $H:$PORT 可达"; break; }
        [ "$i" = 60 ] && log "[warn] LLM 网关 $H:$PORT 不可达（AI 建议或降级，Web 本体继续）"
        sleep 1
    done
else
    log "未配置 LLM_BASE_URL，跳过网关探测"
fi

# 3. 缓冲
sleep 2

exit 0