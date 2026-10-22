"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";
import styles from "./replica-select.module.css";

type Choice = readonly [value: string, label: string];
type Placement = { left: number; width: number; top?: number; bottom?: number; maxHeight: number };

export function ReplicaSelect({ value, onChange, options, label }: {
  value: string;
  onChange: (value: string) => void;
  options: readonly Choice[];
  label: string;
}) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [placement, setPlacement] = useState<Placement>();
  const selected = Math.max(0, options.findIndex(option => option[0] === value));
  const close = (restoreFocus = false) => {
    setPlacement(undefined);
    if (restoreFocus) trigger.current?.focus();
  };
  const open = () => {
    const rect = trigger.current?.getBoundingClientRect();
    if (!rect) return;
    const below = window.innerHeight - rect.bottom - 12;
    const above = rect.top - 12;
    const useAbove = below < 180 && above > below;
    setPlacement({
      left: Math.max(8, Math.min(rect.left, window.innerWidth - rect.width - 8)),
      width: rect.width,
      ...(useAbove ? { bottom: window.innerHeight - rect.top + 6 } : { top: rect.bottom + 6 }),
      maxHeight: Math.min(280, Math.max(96, useAbove ? above : below)),
    });
    requestAnimationFrame(() => menu.current?.querySelectorAll<HTMLButtonElement>("[role=option]")[selected]?.focus());
  };
  useEffect(() => {
    if (!placement) return;
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !menu.current?.contains(event.target) && !trigger.current?.contains(event.target)) setPlacement(undefined);
    };
    const viewportChange = (event: Event) => {
      if (event.target instanceof Node && menu.current?.contains(event.target)) return;
      setPlacement(undefined);
    };
    document.addEventListener("pointerdown", outside);
    window.addEventListener("resize", viewportChange);
    window.addEventListener("scroll", viewportChange, true);
    return () => {
      document.removeEventListener("pointerdown", outside);
      window.removeEventListener("resize", viewportChange);
      window.removeEventListener("scroll", viewportChange, true);
    };
  }, [placement]);

  return <>
    <button ref={trigger} type="button" className={`${styles.trigger} ${placement ? styles.open : ""}`} aria-label={label} aria-haspopup="listbox" aria-expanded={!!placement} aria-controls={placement ? id : undefined} onClick={() => placement ? close() : open()} onKeyDown={event => {
      if (["ArrowDown", "ArrowUp"].includes(event.key)) { event.preventDefault(); open(); }
    }}>
      <span>{options[selected]?.[1]}</span><ChevronDown size={14} aria-hidden="true" />
    </button>
    {placement && createPortal(<div ref={menu} id={id} className={styles.menu} style={placement} role="listbox" aria-label={label} onKeyDown={event => {
      if (event.key === "Escape") { event.preventDefault(); close(true); return; }
      if (event.key === "Tab") { close(true); return; }
      const buttons = [...(menu.current?.querySelectorAll<HTMLButtonElement>("[role=option]") ?? [])];
      const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
      const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : event.key === "ArrowDown" ? (current + 1) % buttons.length : event.key === "ArrowUp" ? (current - 1 + buttons.length) % buttons.length : -1;
      if (next >= 0) { event.preventDefault(); buttons[next]?.focus(); }
    }}>
      {options.map(([key, text]) => <button key={key} type="button" role="option" aria-selected={value === key} className={value === key ? styles.selected : ""} onClick={() => { onChange(key); close(true); }}><span>{text}</span>{value === key && <Check size={14} aria-hidden="true" />}</button>)}
    </div>, document.body)}
  </>;
}
