"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import baseStyles from "./video-studio.module.css";
import pickerStyles from "./selection-controls.module.css";
const styles = { ...baseStyles, ...pickerStyles };

export function Brand({ small = false }: { small?: boolean }) {
  return <span className={`${styles.brand} ${small ? styles.brandSmall : ""}`}><img src="/polaris-mark.svg" alt="" /><span><b>极光商绘<span className={styles.brandDivider}> / </span><em>视频空间</em></b><small>POLARIS VIDEO STUDIO</small></span></span>;
}

export function Dialog({ title, children, onClose, wide = false, className = "", closeDisabled = false }: { title: string; children: ReactNode; onClose: () => void; wide?: boolean; className?: string; closeDisabled?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    const previous = document.activeElement;
    dialog?.showModal();
    return () => { dialog?.close(); if (previous instanceof HTMLElement) previous.focus(); };
  }, []);
  return <dialog ref={ref} aria-labelledby={titleId} className={`${styles.dialog} ${wide ? styles.dialogWide : ""} ${className}`} onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }} onClose={event => { event.stopPropagation(); onClose(); }} onClick={event => { if (event.target === event.currentTarget) { event.stopPropagation(); onClose(); } }}>
    <div className={styles.dialogInner}><header><h2 id={titleId}>{title}</h2><button type="button" className={styles.iconButton} aria-label="关闭弹窗" disabled={closeDisabled} onClick={onClose}><X size={20} /></button></header>{children}</div>
  </dialog>;
}

export function Empty({ icon, title, description, action }: { icon: ReactNode; title: string; description: string; action?: ReactNode }) {
  return <div className={styles.empty}><div className={styles.emptyIcon}>{icon}</div><h3>{title}</h3><p>{description}</p>{action}</div>;
}

export function PickerTabs({ label, items, value, onChange }: { label: string; items: { id: string; label: string; icon: ReactNode }[]; value: string; onChange: (value: string) => void }) {
  return <div className={styles.pickerTabs} role="tablist" aria-label={label}>{items.map((item, index) => <button key={item.id} type="button" role="tab" aria-selected={value === item.id} tabIndex={value === item.id ? 0 : -1} onClick={() => onChange(item.id)} onKeyDown={event => {
    const next = event.key === "ArrowRight" ? (index + 1) % items.length : event.key === "ArrowLeft" ? (index + items.length - 1) % items.length : event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : -1;
    if (next < 0) return;
    event.preventDefault(); onChange(items[next].id);
    event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("button")[next]?.focus();
  }}>{item.icon}{item.label}</button>)}</div>;
}

export function PickerFooter({ selected, hint, disabled, applyLabel, onApply, onClose }: { selected?: ReactNode; hint?: string; disabled: boolean; applyLabel: string; onApply: () => void; onClose: () => void }) {
  return <footer className={styles.pickerFooter}><div className={styles.pickerSelection}>{selected ? <><span className={styles.selectedPill}>已选</span><b>{selected}</b></> : <span>请选择一个选项</span>}{hint && <small>{hint}</small>}</div><button type="button" className={styles.outlineButton} onClick={onClose}>取消</button><button type="button" className={styles.primaryButton} disabled={disabled} onClick={onApply}>{applyLabel}</button></footer>;
}
