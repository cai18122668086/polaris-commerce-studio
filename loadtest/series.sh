#!/usr/bin/env bash
# 按 10 → 25 → 50 VU 依次跑三个 5 分钟阶段；某阶段被 guard 叫停就等主机安静后重跑（最多 RETRIES 次）。
# 用法：series.sh <label> [截止时间 epoch，默认 07:20 北京时间]；每个阶段一直重试到成功或到截止时间
set -u
LABEL=${1:?label}; DEADLINE=${2:-$(date -d 'today 07:20' +%s)}
RETRIES=${RETRIES:-1000}
cd "$(dirname "$0")"
for p in ${PHASES:-p10 p25 p50}; do
  for try in $(seq 1 "$RETRIES"); do
    now=$(date +%s); [ $((now + 420)) -gt "$DEADLINE" ] && { echo "deadline reached before $p"; exit 4; }
    echo "=== $LABEL $p try $try $(date '+%T')"
    WAIT_MAX=$(( DEADLINE - now - 420 > 900 ? 900 : DEADLINE - now - 420 )) ./run.sh "$LABEL" "$p" | grep -E 'preflight|k6 exit|GUARD|^run |^total|status0'
    R=$(ls -d "$HOME"/work/loadtest/runs/*-"$LABEL"-"$p" 2>/dev/null | tail -1)
    if [ -n "$R" ] && ! grep -q 'GUARD TRIPPED' "$R/meta.txt" && grep -qE 'k6 exit=(0|99) ' "$R/meta.txt"; then break; fi
    sleep 60
  done
done
