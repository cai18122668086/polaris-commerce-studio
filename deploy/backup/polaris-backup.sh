#!/usr/bin/env bash
# 极光商绘备份：PostgreSQL（pg_dump 自定义格式，压缩）+ MinIO 镜像（mc mirror），带保留期。
#
# 用法：
#   polaris-backup.sh --pg-container NAME --minio-container NAME --minio-env FILE --target DIR [选项]
# 选项：
#   --db NAME              数据库名（默认 polaris）
#   --db-user NAME         数据库用户（默认 polaris）
#   --bucket NAME          要镜像的桶（默认：全部桶）
#   --keep-days N          数据库备份保留天数（默认 14）
#   --compress N           pg_dump 压缩级别 0-9（默认 6）
#   --no-minio             只备份数据库
#   --dry-run              只打印将执行的动作
# --minio-env 文件需含 MINIO_ROOT_USER= / MINIO_ROOT_PASSWORD=（或 MINIO_ACCESS_KEY / MINIO_SECRET_KEY），脚本不会打印它们。
#
# 产物：
#   DIR/pg/<db>-YYYYmmddTHHMMSSZ.dump    pg_dump -Fc（含 supertokens 表，与业务表同库）
#   DIR/pg/<db>-...dump.sha256 / .counts  校验和与逐表行数（恢复演练用来对比）
#   DIR/minio/<bucket>/...                mc mirror 的增量镜像（不加 --remove：源端删除的对象在镜像里保留，靠 --keep-days 外的人工清理）
#   DIR/backup.log                        每次运行的结果
# 退出码非 0 表示失败（适合 systemd OnFailure= 报警）。
#
# 只用 docker exec / docker run --rm 调用容器里自带的 pg_dump 和 mc，主机不需要装客户端。
# 不会停止、重启或修改任何容器；pg_dump 是在线一致性快照（单事务），对业务只有读负载。
set -euo pipefail

PG_CONTAINER="" MINIO_CONTAINER="" MINIO_ENV="" TARGET="" DB=polaris DB_USER=polaris BUCKET=""
KEEP_DAYS=14 COMPRESS=6 DO_MINIO=1 DRY=0
MC_IMAGE=${POLARIS_BACKUP_MC_IMAGE:-minio/minio@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e}
DOCKER=${DOCKER:-docker}

while [ $# -gt 0 ]; do
  case "$1" in
    --pg-container) PG_CONTAINER=$2; shift 2 ;;
    --minio-container) MINIO_CONTAINER=$2; shift 2 ;;
    --minio-env) MINIO_ENV=$2; shift 2 ;;
    --target) TARGET=$2; shift 2 ;;
    --db) DB=$2; shift 2 ;;
    --db-user) DB_USER=$2; shift 2 ;;
    --bucket) BUCKET=$2; shift 2 ;;
    --keep-days) KEEP_DAYS=$2; shift 2 ;;
    --compress) COMPRESS=$2; shift 2 ;;
    --no-minio) DO_MINIO=0; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
[ -n "$PG_CONTAINER" ] && [ -n "$TARGET" ] || { echo "need --pg-container and --target" >&2; exit 2; }
if [ "$DO_MINIO" = 1 ]; then [ -n "$MINIO_CONTAINER" ] && [ -r "$MINIO_ENV" ] || { echo "need --minio-container and readable --minio-env (or --no-minio)" >&2; exit 2; }; fi
[[ "$KEEP_DAYS" =~ ^[0-9]+$ ]] && [[ "$COMPRESS" =~ ^[0-9]$ ]] || { echo "bad --keep-days/--compress" >&2; exit 2; }

TS=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$TARGET/pg" "$TARGET/minio"
LOG="$TARGET/backup.log"
log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG" >&2; }
run() { if [ "$DRY" = 1 ]; then echo "DRY: $*" >&2; else "$@"; fi; }

# 同一目标目录同时只允许一个备份
exec 9>"$TARGET/.lock"
flock -n 9 || { log "another backup is running for $TARGET"; exit 75; }

# ---------- PostgreSQL ----------
DUMP="$TARGET/pg/$DB-$TS.dump"
log "pg_dump start container=$PG_CONTAINER db=$DB -> $DUMP"
t0=$(date +%s)
if [ "$DRY" = 0 ]; then
  $DOCKER exec "$PG_CONTAINER" pg_dump -U "$DB_USER" -d "$DB" -Fc -Z "$COMPRESS" --no-owner >"$DUMP.part"
  # 校验 dump 可读（列出目录）后才转正
  $DOCKER exec -i "$PG_CONTAINER" pg_restore -l >/dev/null <"$DUMP.part"
  mv "$DUMP.part" "$DUMP"
  sha256sum "$DUMP" | awk '{print $1}' >"$DUMP.sha256"
  # 逐表精确行数，与 dump 同一时刻附近采集（在线库，演练比对时允许备份后新增）
  $DOCKER exec "$PG_CONTAINER" psql -U "$DB_USER" -d "$DB" -AtF $'\t' -c "
    select format('%I.%I', schemaname, relname) from pg_stat_user_tables order by 1" |
  while read -r t; do
    printf '%s\t%s\n' "$t" "$($DOCKER exec "$PG_CONTAINER" psql -U "$DB_USER" -d "$DB" -Atc "select count(*) from $t")"
  done >"$DUMP.counts"
fi
log "pg_dump ok size=$( [ "$DRY" = 0 ] && du -h "$DUMP" | cut -f1 || echo -) tables=$( [ "$DRY" = 0 ] && wc -l <"$DUMP.counts" || echo -) secs=$(( $(date +%s) - t0 ))"

# ---------- MinIO ----------
if [ "$DO_MINIO" = 1 ]; then
  NET=$($DOCKER inspect --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$MINIO_CONTAINER" | awk '{print $1}')
  HOSTNAME_IN_NET=$($DOCKER inspect --format '{{.Name}}' "$MINIO_CONTAINER" | sed 's#^/##')
  # 凭据通过 env 文件传给 mc 容器，不出现在命令行/日志里
  ENVF=$(mktemp); trap 'rm -f "$ENVF"' EXIT; chmod 600 "$ENVF"
  (
    set -a; . "$MINIO_ENV"; set +a
    U=${MINIO_ROOT_USER:-${MINIO_ACCESS_KEY:-}}; P=${MINIO_ROOT_PASSWORD:-${MINIO_SECRET_KEY:-}}
    [ -n "$U" ] && [ -n "$P" ] || { echo "minio credentials missing in $MINIO_ENV" >&2; exit 2; }
    echo "MC_HOST_src=http://$U:$P@$HOSTNAME_IN_NET:9000" >"$ENVF"
  )
  SRC="src${BUCKET:+/$BUCKET}"
  DST="/backup${BUCKET:+/$BUCKET}"
  log "mc mirror start $MINIO_CONTAINER/${BUCKET:-*} -> $TARGET/minio"
  t0=$(date +%s)
  run $DOCKER run --rm --network "$NET" --env-file "$ENVF" --user "$(id -u):$(id -g)" \
    -e HOME=/tmp -v "$(cd "$TARGET/minio" && pwd):/backup" --entrypoint mc "$MC_IMAGE" \
    mirror --overwrite --preserve --quiet "$SRC" "$DST" >>"$LOG" 2>&1
  OBJS=$(find "$TARGET/minio" -type f | wc -l)
  log "mc mirror ok objects_in_mirror=$OBJS size=$(du -sh "$TARGET/minio" | cut -f1) secs=$(( $(date +%s) - t0 ))"
fi

# ---------- 保留期 ----------
if [ "$DRY" = 0 ]; then
  n=$(find "$TARGET/pg" -maxdepth 1 -name "$DB-*.dump*" -mtime +"$KEEP_DAYS" -print -delete | wc -l)
  log "retention: removed $n files older than $KEEP_DAYS days"
fi
log "backup done ts=$TS"
