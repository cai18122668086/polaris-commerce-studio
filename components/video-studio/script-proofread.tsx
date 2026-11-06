"use client";

import { Check, FilePenLine } from "lucide-react";
import { Dialog } from "./studio-primitives";
import styles from "./generation-details.module.css";
import base from "./video-studio.module.css";

export function ScriptProofread({ original, text, onChange, onSave, onClose }: { original:string; text:string; onChange:(text:string)=>void; onSave:()=>void; onClose:()=>void }) {
  const same = original === text;
  return <Dialog title="原文校对" wide onClose={onClose}>
    <p className={styles.proofreadIntro}>对照参考原文，核对品牌、价格与规格后保存。</p>
    <div className={styles.proofread}>
      <label><span>参考原文<small>只读保留</small></span><textarea aria-label="校对原文" readOnly value={original || "暂无参考原文"} /></label>
      <label><span>当前配音稿<small>{text.length} / 3000 字</small></span><textarea aria-label="校对配音稿" value={text} maxLength={3000} onChange={event=>onChange(event.target.value)} /></label>
    </div>
    <p className={styles.proofreadStatus}>{same ? <Check size={13} /> : <FilePenLine size={13} />}{same ? "与参考原文一致" : "已独立编辑，原始参考文稿保留"}</p>
    <footer className={styles.actions}><button type="button" className={base.outlineButton} onClick={onClose}>返回编辑</button><button type="button" className={base.primaryButton} onClick={onSave}><Check size={14} />保存校对稿</button></footer>
  </Dialog>;
}
