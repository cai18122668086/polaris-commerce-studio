"""视频空间的磁盘清理（B14）：editing-maintenance 每轮调用，按间隔真正执行。

只清三类可再生 / 无人引用的文件：
1. 封面候选：超过保留天数（默认 14 天）、不在生成中、且没有被任何作品条目的
   ``cover_asset_id`` 引用（含已软删除的作品，文件保留）的候选——连同它们的
   祖先候选（换字用的底图）一起排除。删除目录后把行标成 ``COVER_EXPIRED``，
   候选列表不再返回。
2. 作品海报缓存 ``posters/``：按最近访问时间（命中时会 touch）淘汰到上限以下；
   海报随时可由成片重新生成。
3. 免费素材下载缓存：沿用 ``video_editing_stock_fetch.evict``（1G 上限）。

``python -m app.video_media_cleanup --dry-run`` 只列出将删除的文件，不动任何东西。
"""

from __future__ import annotations

import argparse
import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .video_cover_models import VideoCoverCandidateRecord
from .video_editing_stock_fetch import evict as evict_stock
from .video_editing_stock_fetch import usage as stock_usage
from .video_work_models import VideoWorkItemRecord

logger = logging.getLogger(__name__)

EXPIRED = "COVER_EXPIRED"
ACTIVE = {"queued", "running"}
# 关键帧临时目录 work-<id> 正常处理完就删；残留超过一天的视为中断遗留。
WORK_DIR_GRACE = timedelta(days=1)
WARMUP_SECONDS = 600


@dataclass
class CleanupReport:
    dry_run: bool
    covers: int = 0
    cover_bytes: int = 0
    posters: int = 0
    poster_bytes: int = 0
    stock_bytes: int = 0
    stock_total: int = 0
    files: list[str] = field(default_factory=list)

    @property
    def freed(self) -> int:
        return self.cover_bytes + self.poster_bytes + self.stock_bytes

    def summary(self) -> str:
        verb = "将删除" if self.dry_run else "已删除"
        mb = 1048576
        title = "视频清理（演练）" if self.dry_run else "视频清理"
        return (
            f"{title}：{verb}封面候选 {self.covers} 个"
            f"（{self.cover_bytes / mb:.1f}MB）、"
            f"海报缓存 {self.posters} 个（{self.poster_bytes / mb:.1f}MB）、"
            f"免费素材缓存 {self.stock_bytes / mb:.1f}MB；"
            f"共腾出 {self.freed / mb:.1f}MB；"
            f"素材缓存现 {self.stock_total / mb:.1f}MB"
        )


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if not path.is_dir():
        return 0
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def referenced_cover_ids(session: Session) -> set[str]:
    """被作品条目引用的封面，以及它们的祖先候选（换字底图）。"""

    keep = {
        value
        for value in session.scalars(
            select(VideoWorkItemRecord.cover_asset_id)
            .where(VideoWorkItemRecord.cover_asset_id.is_not(None))
            .distinct()
        )
        if value
    }
    frontier = set(keep)
    while frontier:
        parents = {
            value
            for value in session.scalars(
                select(VideoCoverCandidateRecord.parent_id).where(
                    VideoCoverCandidateRecord.id.in_(sorted(frontier)),
                    VideoCoverCandidateRecord.parent_id.is_not(None),
                )
            )
            if value and value not in keep
        }
        keep |= parents
        frontier = parents
    return keep


def expired_cover_candidates(
    session: Session, retention_days: int, now: datetime | None = None
) -> list[VideoCoverCandidateRecord]:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    keep = referenced_cover_ids(session)
    # 年轻候选（换字子图）还可能要用祖先的底图，祖先一并保留。
    young_parents = set(
        session.scalars(
            select(VideoCoverCandidateRecord.parent_id).where(
                VideoCoverCandidateRecord.created_at >= cutoff,
                VideoCoverCandidateRecord.parent_id.is_not(None),
            )
        )
    )
    rows = session.scalars(
        select(VideoCoverCandidateRecord)
        .where(
            VideoCoverCandidateRecord.created_at < cutoff,
            VideoCoverCandidateRecord.status.not_in(sorted(ACTIVE)),
        )
        .order_by(VideoCoverCandidateRecord.created_at)
    )
    return [
        row
        for row in rows
        if row.id not in keep
        and row.id not in young_parents
        and row.error_code != EXPIRED
    ]


def clean_covers(
    session: Session, settings: Any, report: CleanupReport, now: datetime | None
) -> None:
    root = Path(settings.video_media_dir) / "covers"
    for row in expired_cover_candidates(
        session, settings.video_cover_candidate_retention_days, now
    ):
        folder = root / row.id
        report.covers += 1
        report.cover_bytes += _size(folder)
        if folder.exists():
            report.files.append(str(folder))
        if not report.dry_run:
            shutil.rmtree(folder, ignore_errors=True)
            row.status, row.error_code, row.files = "failed", EXPIRED, {}
    if not report.dry_run:
        session.commit()
    if root.is_dir():
        edge = time.time() - WORK_DIR_GRACE.total_seconds()
        for work in root.glob("work-*"):
            if work.is_dir() and work.stat().st_mtime < edge:
                report.cover_bytes += _size(work)
                report.files.append(str(work))
                if not report.dry_run:
                    shutil.rmtree(work, ignore_errors=True)


def clean_posters(settings: Any, report: CleanupReport) -> None:
    root = Path(settings.video_media_dir) / "posters"
    if not root.is_dir():
        return
    rows = sorted(
        (path.stat().st_mtime, path.stat().st_size, path)
        for path in root.iterdir()
        if path.is_file()
    )
    total = sum(size for _, size, _ in rows)
    for _, size, path in rows:
        if total <= settings.video_poster_cache_max_bytes:
            break
        total -= size
        report.posters += 1
        report.poster_bytes += size
        report.files.append(str(path))
        if not report.dry_run:
            path.unlink(missing_ok=True)


def clean_stock(settings: Any, report: CleanupReport) -> None:
    total, rows = stock_usage(settings)
    cap = settings.video_stock_cache_max_bytes
    if report.dry_run:
        over = total
        for _, size, path in sorted(rows):
            if over <= cap:
                break
            over -= size
            report.stock_bytes += size
            report.files.append(str(path))
        report.stock_total = total - report.stock_bytes
        return
    report.stock_bytes = evict_stock(settings)
    report.stock_total = stock_usage(settings)[0]


def run(
    factory: sessionmaker[Session],
    settings: Any,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> CleanupReport:
    report = CleanupReport(dry_run=dry_run)
    with factory() as session:
        clean_covers(session, settings, report, now)
    clean_posters(settings, report)
    clean_stock(settings, report)
    logger.info(report.summary())
    return report


class Scheduler:
    """maintenance 每 30 秒一轮；清理按配置的间隔执行（默认每小时）。"""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        # 启动后先等一会儿再跑第一轮（部署/重启后可先手动 --dry-run 看清单）。
        interval = settings.video_media_cleanup_interval_seconds
        self.last = time.monotonic() - max(0, interval - WARMUP_SECONDS)

    def tick(self, factory: sessionmaker[Session]) -> CleanupReport | None:
        interval = self.settings.video_media_cleanup_interval_seconds
        if interval <= 0 or time.monotonic() - self.last < interval:
            return None
        self.last = time.monotonic()
        try:
            return run(factory, self.settings)
        except Exception:
            logger.exception("视频清理失败，下一轮重试")
            return None


def main() -> None:
    from .config import Settings
    from .database import build_database_for

    parser = argparse.ArgumentParser(description="视频空间磁盘清理")
    parser.add_argument("--dry-run", action="store_true", help="只列出将删除的文件")
    parser.add_argument("--retention-days", type=int, help="临时覆盖封面候选保留天数")
    parser.add_argument("--poster-cap-mb", type=int, help="临时覆盖海报缓存上限")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings()
    if args.retention_days is not None:
        if args.retention_days < 1:
            parser.error("--retention-days 至少 1 天")
        settings = settings.model_copy(
            update={"video_cover_candidate_retention_days": args.retention_days}
        )
    if args.poster_cap_mb is not None:
        settings = settings.model_copy(
            update={"video_poster_cache_max_bytes": args.poster_cap_mb * 1048576}
        )
    engine, factory = build_database_for(settings)
    try:
        report = run(factory, settings, dry_run=args.dry_run)
        for path in report.files:
            print(path)
        print(report.summary())
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
