"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Copy, Download, Pause, Play, Volume2, VolumeX, X } from "lucide-react";
import { mediaUrl } from "@/lib/api/base-url";
import { finishHref } from "@/features/video-studio/flow-params";
import { neighbour, shortDate, splitTopics, type WorkCard } from "@/features/video-studio/works";
import { coverImageUrl, useWorkVideo } from "@/features/video-studio/use-finishing";
import styles from "./finish-works.module.css";

type Notify = (text: string, tone?: "success" | "error" | "info") => void;

/** 点开作品：居中手机外框里自动播放，旁边是完整标题、正文与口播稿；←/→ 切换，Esc 关闭。 */
export function PhonePreview({ workspaceId, cards, current, onMove, onClose, notify }: {
  workspaceId: string;
  cards: WorkCard[];
  current: WorkCard;
  onMove: (key: string) => void;
  onClose: () => void;
  notify: Notify;
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
  const previous = neighbour(cards, current.key, -1);
  const next = neighbour(cards, current.key, 1);
  const cover = current.coverId ? mediaUrl(coverImageUrl(workspaceId, current.coverId)) : undefined;

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

  const toggle = () => {
    const element = player.current;
    if (!element) return;
    if (element.paused) { void element.play(); setPaused(false); } else { element.pause(); setPaused(true); }
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
        <div className={styles.phoneScreen}>
          {src ? <video key={current.key} ref={player} className={styles.phoneVideo} src={mediaUrl(src)} poster={cover} autoPlay muted={muted} loop playsInline onClick={toggle} onPause={() => setPaused(true)} onPlay={() => setPaused(false)} />
            : cover ? <img className={styles.phoneVideo} src={cover} alt="" /> : <div className={styles.phoneEmpty}>视频读取中</div>}
          <div className={styles.phoneOverlay}>
            <b>{current.title}</b>
            {current.body && <p>{splitTopics(current.body).map((part, index) => part.topic ? <span key={index} className={styles.topic}>{part.text}</span> : part.text)}</p>}
          </div>
          <div className={styles.phoneControls}>
            <button type="button" onClick={toggle} aria-label={paused ? "播放" : "暂停"}>{paused ? <Play size={16} /> : <Pause size={16} />}</button>
            <button type="button" onClick={() => setMuted(value => !value)} aria-label={muted ? "打开声音" : "静音"}>{muted ? <VolumeX size={16} /> : <Volume2 size={16} />}</button>
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
        {current.itemId && <a className={styles.linkButton} href={finishHref({ item: current.itemId })}>重新编辑封面和文案</a>}
        <p className={styles.keys}>← → 切换作品 · Esc 关闭</p>
      </aside>
    </div>
  </div>;
}
