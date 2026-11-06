"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AlertCircle, CheckCircle2, Info, TriangleAlert, X } from "lucide-react";
import styles from "./studio-workflow.module.css";

export type ToastTone = "success" | "error" | "info" | "warning";
export type ToastMessage = { id: number; text: string; tone: ToastTone };

export function StudioToast({ message, onClose, contextKey }: { message: ToastMessage; onClose: () => void; contextKey?: string | null }) {
  const ref = useRef<HTMLDivElement>(null);
  const [host, setHost] = useState<HTMLElement | null>(null);
  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (active) setHost(document.querySelector<HTMLDialogElement>("dialog[open]") ?? document.body);
    });
    return () => { active = false; };
  }, [message.id, contextKey]);
  useEffect(() => {
    const notice = ref.current;
    notice?.showPopover?.();
    return () => { if (notice?.matches(":popover-open")) notice.hidePopover(); };
  }, [message.id, host]);
  useEffect(() => {
    const timer = setTimeout(onClose, message.tone === "error" ? 8000 : 5500);
    return () => clearTimeout(timer);
  }, [message.id, message.tone, onClose]);
  const Icon = { success: CheckCircle2, error: AlertCircle, info: Info, warning: TriangleAlert }[message.tone];
  if (!host) return null;
  return createPortal(<div ref={ref} popover="manual" className={styles.noticeToast} data-tone={message.tone} role={message.tone === "error" ? "alert" : "status"}>
    <span className={styles.toastIcon}><Icon size={21} /></span><div><b>{{ success: "操作成功", error: "操作未完成", info: "提示", warning: "请留意" }[message.tone]}</b><p>{message.text}</p></div><button type="button" aria-label="关闭提示" onClick={onClose}><X size={17} /></button>
  </div>, host);
}
