"use client";

import { useState } from "react";
import { Check, Clock3, Copy, FileText, History, RotateCcw } from "lucide-react";
import type { VideoContent, VideoVersion } from "@/features/video-studio/projects";
import { Dialog } from "./studio-primitives";
import styles from "./studio-workflow.module.css";

export function ScriptHistory({ versions, currentText, onRestore, onCopy, onClose }: {
  versions: VideoVersion[]; currentText: string; onRestore: (snapshot: VideoContent) => void;
  onCopy: (text: string) => void; onClose: () => void;
}) {
  const hasText = versions.some(version => version.snapshot.draft.text.trim());
  const [hideBlank, setHideBlank] = useState(hasText);
  const [confirmedOnly, setConfirmedOnly] = useState(false);
  const [selectedId, setSelectedId] = useState(versions.find(version => version.snapshot.draft.text.trim())?.id || versions[0]?.id);
  const visible = versions.filter(version => (!hideBlank || version.snapshot.draft.text.trim()) && (!confirmedOnly || version.kind === "confirmed"));
  const selected = visible.find(version => version.id === selectedId) || visible[0];
  const formatDate = (date: string) => new Date(date).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });

  return <Dialog title="文案版本" wide className={styles.historyDialog} onClose={onClose}>
    <p className={styles.dialogDescription}>先查看完整文案，再决定是否恢复。历史版本会继续保留。</p>
    <div className={styles.historyFilters}>
      <div role="group" aria-label="版本类型"><button type="button" aria-pressed={!confirmedOnly} onClick={() => setConfirmedOnly(false)}>全部版本 <span>{versions.length}</span></button><button type="button" aria-pressed={confirmedOnly} onClick={() => setConfirmedOnly(true)}>已确认</button></div>
      <label><input type="checkbox" checked={hideBlank} onChange={event => setHideBlank(event.target.checked)} />隐藏空白版本</label>
    </div>
    <div className={styles.historyLayout}>
      <nav className={styles.versionList} aria-label="选择文案版本">
        {visible.map((version, index) => <button type="button" key={version.id} aria-current={selected?.id === version.id ? "true" : undefined} onClick={() => setSelectedId(version.id)}>
          <span className={styles.versionHeading}><span className={version.kind === "confirmed" ? styles.confirmedTag : styles.draftTag}>{version.kind === "confirmed" ? <Check size={12} /> : <FileText size={12} />}{version.kind === "confirmed" ? "已确认" : version.kind === "library" ? "已收藏" : "草稿"}</span><small>#{versions.length - versions.findIndex(row => row.id === version.id)}</small></span>
          <time dateTime={version.created_at}>{formatDate(version.created_at)}</time>
          <p>{version.snapshot.draft.text || "空白草稿"}</p>
          <span className={styles.versionLength}>{version.snapshot.draft.text.length} 字{index === 0 && !confirmedOnly && " · 最近版本"}</span>
        </button>)}
        {!visible.length && <div className={styles.historyEmpty}><History size={24} /><b>暂无匹配版本</b><p>调整筛选查看其他版本。</p></div>}
      </nav>
      <section className={styles.versionDetail} aria-label="版本完整文案" aria-live="polite">
        {selected ? <><header><div><h3>{selected.kind === "confirmed" ? "已确认文案" : "历史草稿"}</h3><span><Clock3 size={13} />{formatDate(selected.created_at)} · {selected.snapshot.draft.text.length} 字</span></div><button type="button" className={styles.quietButton} disabled={!selected.snapshot.draft.text} onClick={() => onCopy(selected.snapshot.draft.text)}><Copy size={14} />复制全文</button></header>
          {selected.snapshot.draft.text === currentText && <div className={styles.sameText}><Check size={13} />与当前编辑器文案一致</div>}
          <div key={selected.id} className={styles.versionFullText} tabIndex={0}>{selected.snapshot.draft.text || "此版本尚未填写文案。"}</div>
        </> : <div className={styles.historyEmpty}><FileText size={28} /><b>选择一个版本查看全文</b></div>}
      </section>
    </div>
    <footer className={styles.historyFooter}><span>恢复后仍可继续编辑</span><button type="button" className={styles.secondaryButton} onClick={onClose}>返回编辑</button><button type="button" className={styles.actionButton} disabled={!selected} onClick={() => selected && onRestore(selected.snapshot)}><RotateCcw size={15} />恢复此版本</button></footer>
  </Dialog>;
}
