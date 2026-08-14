"use client";

import { useState } from "react";
import { ArrowUpRight, Bell, CalendarDays, ExternalLink, X } from "lucide-react";

import { useCurrentAnnouncement } from "@/features/announcements/api/announcements";
import { errorMessage } from "@/lib/api/request";

const DISMISSED_KEY = "polaris.dismissed-announcements";

const kindLabels = {
  info: "公告",
  success: "更新",
  warning: "提醒",
  maintenance: "维护",
} as const;

function readDismissed(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const value = JSON.parse(window.localStorage.getItem(DISMISSED_KEY) ?? "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

export function AnnouncementBanner() {
  const announcement = useCurrentAnnouncement();
  const [dismissedIds, setDismissedIds] = useState<string[]>(readDismissed);
  const [detailOpen, setDetailOpen] = useState(false);

  if (announcement.isLoading || announcement.isError || !announcement.data) return null;
  if (dismissedIds.includes(announcement.data.id)) return null;

  const item = announcement.data;
  const dismiss = () => {
    const next = [...new Set([...dismissedIds, item.id])];
    setDismissedIds(next);
    window.localStorage.setItem(DISMISSED_KEY, JSON.stringify(next.slice(-30)));
  };

  return (
    <>
      <section className={`announcement-banner announcement-banner--${item.kind}`} aria-live="polite">
        <div className="announcement-banner__inner">
          <span className="announcement-banner__icon" aria-hidden="true"><Bell size={16} /></span>
          <div className="announcement-banner__content">
            <span className="announcement-banner__eyebrow">{kindLabels[item.kind]}</span>
            <strong>{item.title}</strong>
            {item.summary && <span>{item.summary}</span>}
          </div>
          <button type="button" className="announcement-banner__detail-button" onClick={() => setDetailOpen(true)}>
            查看详情 <ArrowUpRight size={15} />
          </button>
          <button type="button" className="announcement-banner__close" onClick={dismiss} aria-label="关闭公告">
            <X size={17} />
          </button>
        </div>
      </section>
      {detailOpen && (
        <div className="announcement-dialog-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setDetailOpen(false);
        }}>
          <article className="announcement-dialog" role="dialog" aria-modal="true" aria-labelledby="announcement-dialog-title">
            <div className={`announcement-dialog__accent announcement-dialog__accent--${item.kind}`} />
            <header className="announcement-dialog__header">
              <div>
                <span className="announcement-banner__eyebrow">{kindLabels[item.kind]}</span>
                <h2 id="announcement-dialog-title">{item.title}</h2>
              </div>
              <button type="button" className="icon-button" onClick={() => setDetailOpen(false)} aria-label="关闭公告详情"><X size={18} /></button>
            </header>
            {item.summary && <p className="announcement-dialog__summary">{item.summary}</p>}
            <div className="announcement-dialog__content">{item.content}</div>
            <footer className="announcement-dialog__footer">
              <span><CalendarDays size={15} /> {item.published_at ? new Date(item.published_at).toLocaleDateString("zh-CN") : ""}</span>
              {item.link_url && <a href={item.link_url} target="_blank" rel="noreferrer">打开相关页面 <ExternalLink size={14} /></a>}
              <button type="button" className="button secondary" onClick={dismiss}>知道了</button>
            </footer>
          </article>
        </div>
      )}
    </>
  );
}

export function AnnouncementLoadError() {
  const announcement = useCurrentAnnouncement();
  if (!announcement.isError) return null;
  return <span className="sr-only">{errorMessage(announcement.error)}</span>;
}
