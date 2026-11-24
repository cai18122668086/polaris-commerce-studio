#!/usr/bin/env bash
# 跑一轮压测（总在 guard.sh 保护下）：run.sh <label> [full|smoke]
# 产物：$LT/runs/<时间>-<label>/{k6.csv.gz,summary.json,stats.tsv,queues.tsv,logs/,meta.txt,guard.log 片段}
set -u
LABEL=${1:?label}; STAGES=${2:-full}
LT=${LT:-$HOME/work/loadtest}; REPO=$(cd "$(dirname "$0")" && pwd)
STG=${STG:-$HOME/work/loadstg}
# 预检：最多等 WAIT_MAX 秒，直到 1 分钟负载 < PRE_LOAD 且可用内存 > PRE_AVAIL_MB（连续 3 次，间隔 10 秒）
PRE_LOAD=${PRE_LOAD:-4}; PRE_AVAIL_MB=${PRE_AVAIL_MB:-4500}; WAIT_MAX=${WAIT_MAX:-900}
ok=0; waited=0
while [ $ok -lt 3 ]; do
  l=$(cut -d' ' -f1 /proc/loadavg); a=$(( $(awk '/^MemAvailable:/{print $2}' /proc/meminfo) / 1024 ))
  if awk -v l="$l" -v m="$PRE_LOAD" 'BEGIN{exit !(l<m)}' && [ "$a" -gt "$PRE_AVAIL_MB" ]; then ok=$((ok+1)); else ok=0; fi
  [ $ok -ge 3 ] && break
  [ $waited -ge "$WAIT_MAX" ] && { echo "preflight: host busy for ${WAIT_MAX}s (load1=$l avail=${a}MB), giving up"; exit 3; }
  sleep 10; waited=$((waited+10))
done
echo "preflight ok after ${waited}s (load1=$l avail=${a}MB)"
OUT=$LT/runs/$(date +%Y%m%d-%H%M)-$LABEL-$STAGES; mkdir -p "$OUT/logs"
D="sudo -n docker"
echo "label=$LABEL stages=$STAGES preflight_load1=$l code=$(cat $STG/current-code) commit=$(git -C "$(cat $STG/current-code)" rev-parse --short HEAD) start=$(date -Is)" | tee "$OUT/meta.txt"
RPW=$(grep '^STG_REDIS_PASSWORD=' "$STG/stg.env" | cut -d= -f2)

# 1) 采样器：staging 容器资源 + 队列深度（每 5 秒）
( while :; do
    ts=$(date +%s)
    $D stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' | grep polaris-loadstg | sed "s/^/$ts\t/"
    sleep 5
  done ) >"$OUT/stats.tsv" 2>/dev/null &
SAMPLER=$!
( while :; do
    ts=$(date +%s)
    q=$($D exec -e REDISCLI_AUTH="$RPW" polaris-loadstg-redis-1 sh -c 'for k in default domestic_detail_v431 one_click_replica; do printf "%s=%s " $k $(redis-cli --no-auth-warning llen $k); done' 2>/dev/null)
    echo -e "$ts\t$q"
    sleep 5
  done ) >"$OUT/queues.tsv" &
QSAMPLER=$!

# 2) k6 进程放进独立进程组，guard 杀的是这个组
setsid "$LT/bin/k6" run --quiet --no-color \
  -e USERS="$LT/users.json" -e DATA="$LT/data" -e STAGES="$STAGES" -e OUT="$OUT" -e DEBUG="${DEBUG:-}" \
  --out csv="$OUT/k6.csv.gz" "$REPO/polaris.js" >"$OUT/k6.stdout" 2>"$OUT/k6.stderr" &
K6=$!
echo "$K6" >"$LT/loadgen.pid"
GLINE=$(wc -l <"$LT/guard.log" 2>/dev/null || echo 0)
"$LT/guard.sh" "$LT/loadgen.pid" &
GUARD=$!
echo "k6 pid/pgid=$K6 guard=$GUARD out=$OUT"
wait "$K6"; RC=$?
kill "$GUARD" "$SAMPLER" "$QSAMPLER" 2>/dev/null
echo "k6 exit=$RC end=$(date -Is)" | tee -a "$OUT/meta.txt"
tail -n +"$((GLINE + 1))" "$LT/guard.log" >"$OUT/guard.log"
grep -q TRIP "$OUT/guard.log" && echo "GUARD TRIPPED" | tee -a "$OUT/meta.txt"

# 3) 收集日志与 OOM/重启信息
START=$(sed -n 's/.*start=\([^ ]*\).*/\1/p' "$OUT/meta.txt")
for c in $($D ps -a --format '{{.Names}}' | grep ^polaris-loadstg); do
  $D logs --since "$START" "$c" >"$OUT/logs/$c.log" 2>&1
  $D inspect --format "$c oom={{.State.OOMKilled}} restarts={{.RestartCount}} status={{.State.Status}} started={{.State.StartedAt}}" "$c"
done | tee "$OUT/containers.txt"
python3 -I "$REPO/analyze.py" "$OUT" | tee "$OUT/report.txt"
