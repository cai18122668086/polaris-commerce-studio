#!/usr/bin/env bash
# staging 开关：stg.sh up [baseline|after] | stop | down | status | logs <svc>
set -u
D=$HOME/work/loadstg
cd "$D"
which_code() { case "${1:-baseline}" in baseline) echo "$D/code-baseline";; after) echo "$D/code-after";; *) echo "$1";; esac; }
c() {
  local code="${STG_CODE:-$D/code-baseline}" extra=()
  # 对比轮（code-after）叠加 compose.after.yaml；它的额外环境变量通过 STG_EXTRA_ENV 指向的文件进 x-app
  [ "$(basename "$code")" = code-after ] && extra=(-f "$D/compose.after.yaml")
  sudo -n env STG_CODE="$code" docker compose --env-file "$D/stg.env" -f "$D/compose.yaml" "${extra[@]}" "$@"
}
case "${1:-status}" in
  up) export STG_CODE=$(which_code "${2:-baseline}")
      if [ "$(basename "$STG_CODE")" = code-after ]; then cp "$D/stg-app-after.env" "$D/stg-app-extra.env"; else : >"$D/stg-app-extra.env"; fi; echo "$STG_CODE" > "$D/current-code"; c up -d --force-recreate --remove-orphans ;;
  stop) STG_CODE=$(cat "$D/current-code" 2>/dev/null || echo "$D/code-baseline") c stop ;;
  down) STG_CODE=$(cat "$D/current-code" 2>/dev/null || echo "$D/code-baseline") c down ;;
  status) STG_CODE=$(cat "$D/current-code" 2>/dev/null || echo "$D/code-baseline") c ps --format '{{.Service}}\t{{.Status}}' ;;
  logs) shift; STG_CODE=$(cat "$D/current-code" 2>/dev/null || echo "$D/code-baseline") c logs --no-color "$@" ;;
  *) echo "usage: stg.sh up [baseline|after|DIR] | stop | down | status | logs <svc>"; exit 2 ;;
esac
