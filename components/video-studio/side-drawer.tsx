"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import styles from "./library-drawers.module.css";

/**
 * 右侧抽屉（原生 <dialog> 模态：自带焦点圈定与 Esc 关闭）。
 * 由 open 控制；关闭只通过 onClose 通知外层，抽屉自身不改外层任何状态。
 */
export function SideDrawer({ open, title, description, onClose, closeDisabled = false, footer, children }: { open: boolean; title: string; description?: string; onClose: () => void; closeDisabled?: boolean; footer?: ReactNode; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!open || !dialog) return;
    const previous = document.activeElement;
    if (!dialog.open) dialog.showModal();
    return () => { if (dialog.open) dialog.close(); if (previous instanceof HTMLElement) previous.focus(); };
  }, [open]);
  if (!open) return null;
  const close = () => { if (!closeDisabled) onClose(); };
  return <dialog ref={ref} aria-labelledby={titleId} className={styles.drawer}
    onCancel={event => { event.preventDefault(); event.stopPropagation(); close(); }}
    onClose={event => event.stopPropagation()}
    onClick={event => { if (event.target === event.currentTarget) { event.stopPropagation(); close(); } }}>
    <div className={styles.drawerPanel}>
      <header className={styles.drawerHeader}>
        <div><h2 id={titleId}>{title}</h2>{description && <p>{description}</p>}</div>
        <button type="button" className={styles.closeButton} aria-label="关闭" disabled={closeDisabled} onClick={close}><X size={18} /></button>
      </header>
      <div className={styles.drawerBody}>{children}</div>
      {footer && <footer className={styles.drawerFooter}>{footer}</footer>}
    </div>
  </dialog>;
}
