#!/usr/bin/env bash
# 恢复演练：把 polaris-backup.sh 产出的 dump 恢复进一个临时库，逐表比对行数，再比对 MinIO 镜像对象数，最后删掉临时库。
# 用法：polaris-restore-drill.sh --pg-container NAME --dump FILE [--db-user polaris] [--minio-container NAME --minio-env FILE --mirror DIR]
# 只在 staging 上跑。脚本拒绝在名字含 production 的容器里创建临时库，除非显式 ALLOW_PRODUCTION_DRILL=1。
set -euo pipefail
PG=""; DUMP=""; DB_USER=polaris; MINIO=""; MINIO_ENV=""; MIRROR=""
DOCKER=${DOCKER:-docker}
MC_IMAGE=${POLARIS_BACKUP_MC_IMAGE:-minio/minio@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e}
while [ $# -gt 0 ]; do
  case "$1" in
    --pg-container) PG=$2; shift 2 ;; --dump) DUMP=$2; shift 2 ;; --db-user) DB_USER=$2; shift 2 ;;
    --minio-container) MINIO=$2; shift 2 ;; --minio-env) MINIO_ENV=$2; shift 2 ;; --mirror) MIRROR=$2; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
[ -n "$PG" ] && [ -r "$DUMP" ] || { echo "need --pg-container and readable --dump" >&2; exit 2; }
case "$PG" in *production*) [ "${ALLOW_PRODUCTION_DRILL:-0}" = 1 ] || { echo "refusing to drill inside a production container" >&2; exit 2; } ;; esac

SCRATCH="drill_$(date -u +%Y%m%d%H%M%S)"
psqlc() { $DOCKER exec "$PG" psql -U "$DB_USER" -v ON_ERROR_STOP=1 "$@"; }
cleanup() { psqlc -d postgres -qc "DROP DATABASE IF EXISTS $SCRATCH" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "sha256 check"
[ -r "$DUMP.sha256" ] && [ "$(sha256sum "$DUMP" | awk '{print $1}')" = "$(cat "$DUMP.sha256")" ] && echo "  sha256 ok" || { echo "  sha256 MISMATCH or missing"; exit 1; }

t0=$(date +%s)
psqlc -d postgres -qc "CREATE DATABASE $SCRATCH"
# --no-owner/--no-acl：恢复进临时库不依赖原角色
$DOCKER exec -i "$PG" pg_restore -U "$DB_USER" -d "$SCRATCH" --no-owner --no-acl --exit-on-error <"$DUMP"
echo "restore into $SCRATCH ok in $(( $(date +%s) - t0 ))s"

fail=0; n=0
while IFS=$'\t' read -r table expected; do
  n=$((n+1))
  got=$(psqlc -d "$SCRATCH" -Atc "select count(*) from $table" 2>/dev/null || echo MISSING)
  if [ "$got" != "$expected" ]; then echo "  MISMATCH $table backup_time=$expected restored=$got"; fail=$((fail+1)); fi
done <"$DUMP.counts"
echo "row counts: $n tables compared, $fail mismatches"
psqlc -d "$SCRATCH" -Atc "select 'restored total rows', sum(n_live_tup) from pg_stat_user_tables" >/dev/null

if [ -n "$MINIO" ] && [ -n "$MIRROR" ]; then
  NET=$($DOCKER inspect --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$MINIO" | awk '{print $1}')
  HN=$($DOCKER inspect --format '{{.Name}}' "$MINIO" | sed 's#^/##')
  ENVF=$(mktemp); chmod 600 "$ENVF"; trap 'rm -f "$ENVF"; cleanup' EXIT
  ( set -a; . "$MINIO_ENV"; set +a; echo "MC_HOST_src=http://${MINIO_ROOT_USER:-$MINIO_ACCESS_KEY}:${MINIO_ROOT_PASSWORD:-$MINIO_SECRET_KEY}@$HN:9000" >"$ENVF" )
  src=$($DOCKER run --rm --network "$NET" --env-file "$ENVF" -e HOME=/tmp --entrypoint mc "$MC_IMAGE" ls --recursive --json src 2>/dev/null | grep -c '"type":"file"' || true)
  dst=$(find "$MIRROR" -type f | wc -l)
  echo "minio objects: source=$src mirror=$dst (source may grow after the backup while traffic continues)"
  [ "$dst" -ge 1 ] || { echo "  mirror is empty"; fail=$((fail+1)); }
  # 随机抽 5 个对象比对内容
  for f in $(find "$MIRROR" -type f | shuf -n 5); do
    rel=${f#"$MIRROR"/}
    a=$(sha256sum "$f" | awk '{print $1}')
    b=$($DOCKER run --rm --network "$NET" --env-file "$ENVF" -e HOME=/tmp --entrypoint mc "$MC_IMAGE" cat "src/$rel" 2>/dev/null | sha256sum | awk '{print $1}')
    [ "$a" = "$b" ] && echo "  object ok $rel" || { echo "  object MISMATCH $rel"; fail=$((fail+1)); }
  done
fi
[ "$fail" = 0 ] && echo "DRILL PASSED" || { echo "DRILL FAILED ($fail problems)"; exit 1; }
