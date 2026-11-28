"use client";

import { useEffect, useRef, useState, type TouchEvent } from "react";
import { Check, ChevronLeft, ChevronRight, Copy, Download, Pause, Play, Volume2, VolumeX, X } from "lucide-react";
import { mediaUrl } from "@/lib/api/base-url";
import { finishHref } from "@/features/video-studio/flow-params";
import { neighbour, posterPath, shortDate, splitTopics, type WorkCard } from "@/features/video-studio/works";
import { coverImageUrl, useWorkVideo } from "@/features/video-studio/use-finishing";
import { ConfirmDelete } from "./confirm-delete";
import styles from "./finish-works.module.css";

type Notify = (text: string, tone?: "success" | "error" | "info") => void;

/** 点开作品：居中手机外框里自动播放，旁边是完整标题、正文与口播稿；←/→ 切换，Esc 关闭。 */
export function PhonePreview({ workspaceId, cards, current, accountName, onMove, onClose, notify, onDelete, onTogglePublished, publishing = false }: {
  workspaceId: string;
  accountName: string;
  cards: WorkCard[];
  current: WorkCard;
  onMove: (key: string) => void;
  onClose: () => void;
  notify: Notify;
  /** B1：从作品里移除（页内二次确认）。旧的剪辑成片没有作品条目，不给删。 */
  onDelete?: () => Promise<void>;
  /** C10：已发布标记。 */
  onTogglePublished?: () => void;
  publishing?: boolean;
}) {
  const video = useWorkVideo(workspaceId, current.videoUrl || !current.hasVideo ? null : { editing_task_id: current.editingTaskId, generation_task_id: current.generationTaskId });
  const src = current.videoUrl ?? video.data ?? null;
  const player = useRef<HTMLVideoElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [muted, setMuted] = useState(true);
  // Per-work view state: switching works starts again on 发布文案, playing.
  const [view, setView] = useState<{ key: string; paused: boolean; tab: "post" | "script" }>({ key: current.key, paused: false, tab: "post" });
  const paused = view.key === current.key ? view.paused : false;
  const tab = view.key === current.key ? view.tab : "post";
  const setPaused = (value: boolean) => setView({ key: current.key, paused: value, tab });
  const setTab = (value: "post" | "script") => setView({ key: current.key, paused, tab: value });
  // B3：画面下方的一行「@账号 · 标题」默认收起，点一下展开标题和正文；切换作品时回到收起。
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const expanded = expandedKey === current.key;
  const touch = useRef<{ x: number; y: number } | null>(null);
  const previous = neighbour(cards, current.key, -1);
  const next = neighbour(cards, current.key, 1);
  const posterSource = current.coverId ? coverImageUrl(workspaceId, current.coverId) : posterPath(workspaceId, current);
  const cover = posterSource ? mediaUrl(posterSource) : undefined;

  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = overflow; before?.focus?.(); };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLElement && ["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName)) return;
      if (event.key === "Escape") { event.preventDefault(); onClose(); }
      else if (event.key === "ArrowRight" && next) { event.preventDefault(); onMove(next.key); }
      else if (event.key === "ArrowLeft" && previous) { event.preventDefault(); onMove(previous.key); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [next, previous, onMove, onClose]);

  // React does not write `muted` as an attribute before load, so browsers may
  // block autoplay; mute and start explicitly whenever the work changes.
  useEffect(() => {
    const element = player.current;
    if (!element) return;
    element.muted = true;
    element.play()?.catch(() => setView(view => ({ ...view, paused: true })));
  }, [current.key, src]);

  const toggle = () => {
    const element = player.current;
    if (!element) return;
    if (element.paused) { void element.play(); setPaused(false); } else { element.pause(); setPaused(true); }
  };
  // 手机上左右滑动切换（水平位移 > 56px 且大于竖直位移，避免和页面上下滚动冲突）。
  const onTouchStart = (event: TouchEvent) => { const t = event.touches[0]; touch.current = t ? { x: t.clientX, y: t.clientY } : null; };
  const onTouchEnd = (event: TouchEvent) => {
    const start = touch.current; touch.current = null;
    const t = event.changedTouches[0];
    if (!start || !t) return;
    const dx = t.clientX - start.x, dy = t.clientY - start.y;
    if (Math.abs(dx) < 56 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
    if (dx < 0 && next) onMove(next.key);
    else if (dx > 0 && previous) onMove(previous.key);
  };
  const copy = async (text: string, label: string) => {
    if (!text.trim()) { notify(`这条作品还没有${label}`, "info"); return; }
    try { await navigator.clipboard.writeText(text); notify(`${label}已复制`, "success"); }
    catch { notify("复制没有成功，请手动选中文字复制", "error"); }
  };

  return <div className={styles.previewLayer} role="dialog" aria-modal="true" aria-label={`作品预览：${current.title}`} onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <button ref={closeRef} type="button" className={styles.previewClose} onClick={onClose} aria-label="关闭预览（Esc）"><X size={20} /></button>
    <button type="button" className={`${styles.previewNav} ${styles.previewPrev}`} disabled={!previous} onClick={() => previous && onMove(previous.key)} aria-label="上一条（←）"><ChevronLeft size={22} /></button>
    <button type="button" className={`${styles.previewNav} ${styles.previewNext}`} disabled={!next} onClick={() => next && onMove(next.key)} aria-label="下一条（→）"><ChevronRight size={22} /></button>
    <div className={styles.previewBody}>
      <div className={styles.phone}>
        <div className={styles.phoneScreen} onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
          {/* 视频按 9:16 放在上部，叠字放在画面下方的条里：任何模板的字幕都不会被压住。 */}
          <div className={styles.phoneStage}>
            {src ? <video key={current.key} ref={player} className={styles.phoneVideo} src={mediaUrl(src)} poster={cover} autoPlay muted={muted} loop playsInline onClick={toggle} onPause={() => setPaused(true)} onPlay={() => setPaused(false)} />
              : cover ? <img className={styles.phoneVideo} src={cover} alt="" /> : <div className={styles.phoneEmpty}>视频读取中</div>}
          </div>
          <div className={`${styles.phoneOverlay} ${expanded ? styles.phoneOverlayOpen : ""}`}>
            <button type="button" className={styles.phoneCaption} aria-expanded={expanded} onClick={() => setExpandedKey(expanded ? null : current.key)} title={expanded ? "收起" : "展开标题和正文"}>
              <span className={styles.phoneAccount}>@{accountName}</span>
              <b>{current.title}</b>
              {expanded && current.body && <span className={styles.phoneBody}>{current.body}</span>}
            </button>
            <div className={styles.phoneControls}>
              <button type="button" onClick={toggle} aria-label={paused ? "播放" : "暂停"}>{paused ? <Play size={15} /> : <Pause size={15} />}</button>
              <button type="button" onClick={() => { const next = !muted; setMuted(next); if (player.current) player.current.muted = next; }} aria-label={muted ? "打开声音" : "静音"}>{muted ? <VolumeX size={15} /> : <Volume2 size={15} />}</button>
            </div>
          </div>
        </div>
      </div>
      <aside className={styles.previewInfo}>
        <div className={styles.previewTabs} role="tablist" aria-label="作品文字">
          <button type="button" role="tab" aria-selected={tab === "post"} onClick={() => setTab("post")}>发布文案</button>
          <button type="button" role="tab" aria-selected={tab === "script"} onClick={() => setTab("script")}>口播稿</button>
        </div>
        {tab === "post" ? <div className={styles.previewText} role="tabpanel">
          <h2>{current.title}{current.titleIsFallback && <small>（未设置标题，取自口播稿）</small>}</h2>
          {current.body ? <p>{splitTopics(current.body).map((part, index) => part.topic ? <span key={index} className={styles.topic}>{part.text}</span> : part.text)}</p> : <p className={styles.muted}>还没有发布正文。</p>}
          <time dateTime={current.createdAt}>{shortDate(current.createdAt)}</time>
        </div> : <div className={styles.previewText} role="tabpanel">
          {current.script ? <p className={styles.scriptText}>{current.script}</p> : <p className={styles.muted}>这条作品没有保存口播稿。</p>}
        </div>}
        <div className={styles.previewActions}>
          {src ? <a className={styles.secondary} href={mediaUrl(src)} download><Download size={15} />下载视频</a> : <button type="button" className={styles.secondary} disabled><Download size={15} />下载视频</button>}
          {current.coverId ? <a className={styles.secondary} href={mediaUrl(coverImageUrl(workspaceId, current.coverId, "cover", true))} download><Download size={15} />下载封面</a> : <button type="button" className={styles.secondary} disabled title="这条作品还没有封面"><Download size={15} />下载封面</button>}
          <button type="button" className={styles.ghost} onClick={() => void copy(current.title, "标题")}><Copy size={15} />复制标题</button>
          <button type="button" className={styles.ghost} onClick={() => void copy(current.body, "正文")}><Copy size={15} />复制正文</button>
        </div>
        {onTogglePublished && <div className={styles.previewMarks}>
          <button type="button" className={styles.publishToggle} role="switch" aria-checked={Boolean(current.publishedAt)} disabled={publishing} onClick={onTogglePublished}>
            <span className={styles.publishBox} aria-hidden="true">{current.publishedAt && <Check size={12} strokeWidth={2.6} />}</span>
            {current.publishedAt ? `已发布 · ${shortDate(current.publishedAt)}` : "标记为已发布"}
          </button>
          <small>只是自己的记号，方便筛出还没发的</small>
        </div>}
        <div className={styles.previewLinks}>
          {current.itemId && <a className={styles.linkButton} href={finishHref({ item: current.itemId })}>重新编辑封面和文案</a>}
          {onDelete && <ConfirmDelete onConfirm={onDelete} label="删除这条作品" />}
        </div>
        <p className={styles.keys}><span className={styles.keysDesk}>← → 切换作品 · Esc 关闭</span><span className={styles.keysTouch}>在视频上左右滑动切换作品</span></p>
      </aside>
    </div>
  </div>;
}
