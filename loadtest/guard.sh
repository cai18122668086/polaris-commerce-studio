#!/usr/bin/env bash
# 压测安全阀：每 5 秒检查一次主机与正式站容器，触发任一条件就杀掉压测进程组。
#   - 主机可用内存 < 2.5GB
#   - 1 分钟负载 > 6
#   - 任一正式容器 CPU 连续 3 次 > 其上限的 85%
#   - 任一正式容器重启（RestartCount / StartedAt 变化、消失或非 running）
# 正式容器 = 名字不以 polaris-videodev / polaris-loadstg 开头的所有容器。
# 只读：docker stats --no-stream / docker inspect 元数据，不改任何容器。
# 用法：guard.sh [PIDFILE]   PIDFILE 每行一个要保护的进程（组）号，默认 ~/work/loadtest/loadgen.pid
set -u
D=$HOME/work/loadtest
PIDFILE=${1:-$D/loadgen.pid}
LOG=${GUARD_LOG:-$D/guard.log}
TRIP=${GUARD_TRIP:-$D/guard.tripped}
INTERVAL=${GUARD_INTERVAL:-5}
MIN_AVAIL_KB=${GUARD_MIN_AVAIL_KB:-2621440}   # 2.5 GiB
MAX_LOAD=${GUARD_MAX_LOAD:-6}
CPU_FRAC=${GUARD_CPU_FRAC:-0.85}
CPU_STREAK=${GUARD_CPU_STREAK:-3}
# polaris-ci-*：其他线程跑 CI 的临时容器（如 polaris-ci-pg-tmp），频繁创建/删除、自身 CPU 打满，不属于正式站
EXCLUDE=${GUARD_EXCLUDE:-'^(polaris-videodev|polaris-loadstg|polaris-ci-)'}
DOCKER="sudo -n docker"
declare -A BASE STREAK
log() { echo "$(date '+%F %T') $*" >>"$LOG"; }

kill_loadgen() {
  local why="$1"
  log "TRIP: $why"
  echo "$(date '+%F %T') $why" >>"$TRIP"
  [ -f "$PIDFILE" ] || { log "no pidfile $PIDFILE"; return; }
  while read -r p; do
    [ -n "$p" ] || continue
    if kill -0 "$p" 2>/dev/null; then
      kill -TERM -- "-$p" 2>/dev/null || kill -TERM "$p" 2>/dev/null
      log "sent TERM to pgid/pid $p"
    fi
  done <"$PIDFILE"
  sleep 3
  while read -r p; do
    [ -n "$p" ] || continue
    if kill -0 "$p" 2>/dev/null; then
      kill -KILL -- "-$p" 2>/dev/null || kill -KILL "$p" 2>/dev/null
      log "sent KILL to pgid/pid $p"
    fi
  done <"$PIDFILE"
}

meta() {  # name nanocpus restartcount startedat status
  $DOCKER inspect --format '{{.Name}} {{.HostConfig.NanoCpus}} {{.RestartCount}} {{.State.StartedAt}} {{.State.Status}}' $($DOCKER ps -q) 2>/dev/null \
    | sed 's#^/##' | grep -Ev "$EXCLUDE"
}

log "guard start pidfile=$PIDFILE interval=${INTERVAL}s"
while read -r n c r s st; do BASE[$n]="$r $s"; done < <(meta)
log "baseline: ${#BASE[@]} production containers"

while true; do
  t0=$(date +%s)
  avail=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)
  load1=$(cut -d' ' -f1 /proc/loadavg)
  reasons=()
  [ "$avail" -lt "$MIN_AVAIL_KB" ] && reasons+=("mem_available=${avail}kB<${MIN_AVAIL_KB}kB")
  awk -v l="$load1" -v m="$MAX_LOAD" 'BEGIN{exit !(l>m)}' && reasons+=("load1=$load1>$MAX_LOAD")

  declare -A LIM=()
  seen=()
  while read -r n c r s st; do
    LIM[$n]=$c; seen+=("$n")
    if [ -n "${BASE[$n]:-}" ] && [ "${BASE[$n]}" != "$r $s" ]; then reasons+=("restart:$n(${BASE[$n]} -> $r $s)"); BASE[$n]="$r $s"; fi
    [ "$st" != running ] && reasons+=("not_running:$n($st)")
  done < <(meta)
  for n in "${!BASE[@]}"; do
    printf '%s\n' "${seen[@]}" | grep -qx "$n" || reasons+=("gone:$n")
  done

  top=""
  while read -r n pct; do
    [[ "$n" =~ $EXCLUDE ]] && continue
    pct=${pct%\%}
    c=${LIM[$n]:-0}
    # NanoCpus=0 表示不限，按整机核数算
    limpct=$(awk -v c="$c" -v h="$(nproc)" 'BEGIN{print (c>0? c/1e9*100 : h*100)}')
    if awk -v p="$pct" -v l="$limpct" -v f="$CPU_FRAC" 'BEGIN{exit !(p>l*f)}'; then
      STREAK[$n]=$(( ${STREAK[$n]:-0} + 1 ))
      log "warn cpu $n ${pct}% > ${CPU_FRAC}x${limpct}% streak=${STREAK[$n]}"
      [ "${STREAK[$n]}" -ge "$CPU_STREAK" ] && reasons+=("cpu:$n ${pct}%/${limpct}% x${STREAK[$n]}")
    else
      STREAK[$n]=0
    fi
    top=$(printf '%s\n%s %s' "$top" "$pct" "$n")
  done < <($DOCKER stats --no-stream --format '{{.Name}} {{.CPUPerc}}' 2>/dev/null)
  hot=$(echo "$top" | sort -rn | head -3 | awk 'NF{printf "%s=%s%% ",$2,$1}')
  log "sample avail=$((avail/1024))MB load1=$load1 top: $hot"

  if [ ${#reasons[@]} -gt 0 ]; then kill_loadgen "${reasons[*]}"; fi
  unset LIM
  el=$(( $(date +%s) - t0 ))
  sleep $(( INTERVAL > el ? INTERVAL - el : 1 ))
done
