"use client";

import { useId, useState, type ReactNode } from "react";
import { ChevronDown, FileText } from "lucide-react";
import Link from "next/link";
import styles from "./studio-content.module.css";

export function Disclosure({ title, description, meta, icon, children, defaultOpen = false, group }: { title: string; description?: string; meta?: ReactNode; icon?: ReactNode; children: ReactNode; defaultOpen?: boolean; group?: string }) {
  return <details className={styles.disclosure} name={group} open={defaultOpen || undefined}>
    <summary><span className={styles.sectionIcon}>{icon || <FileText size={17} />}</span><span className={styles.sectionHeading}><b>{title}</b>{description && <small>{description}</small>}</span>{meta && <span className={styles.sectionMeta}>{meta}</span>}<ChevronDown className={styles.chevron} size={16} /></summary>
    <div className={styles.disclosureBody}>{children}</div>
  </details>;
}

export function TextDocument({ text, title = "完整文案", onCopy }: { text: string; title?: string; onCopy?: (text: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const textId = useId();
  const long = text.length > 140 || text.split("\n").length > 4;
  return <section className={styles.document} aria-label={title}>
    <header><span>{title}</span><small>{text.length} 字</small>{onCopy && <button type="button" onClick={() => onCopy(text)}>复制全文</button>}</header>
    <div id={textId} className={styles.documentText} data-expanded={expanded || !long} tabIndex={expanded || !long ? 0 : undefined}>{text || "暂无文案"}</div>
    {long && <button type="button" className={styles.expandText} aria-expanded={expanded} aria-controls={textId} onClick={() => setExpanded(value => !value)}>{expanded ? "收起全文" : "展开全文"}<ChevronDown size={14} /></button>}
  </section>;
}

export function MetadataGrid({ items }: { items: { label: string; value: ReactNode }[] }) {
  return <dl className={styles.metadata}>{items.map(item => <div key={item.label}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}</dl>;
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warning" }) {
  return <div className={styles.notice} data-tone={tone}>{children}</div>;
}

/** 余额不足时的充值入口（积分包在账户中心的会员与积分页） */
export function TopUpLink() {
  return <Link className={styles.topUpLink} href="/account#membership">充值积分</Link>;
}

/** 余额不足：计费按钮已停用，说明原因并给出充值入口 */
export function ShortOfCredits({ credits }: { credits?: number | null }) {
  return <p className={styles.costLine} data-short role="status">{typeof credits === "number" ? `余额不足，本次需 ${credits} 积分` : "余额不足"} · <TopUpLink /></p>;
}

/** Price shown beside a paid action; "按实际用量计费" when no price is configured. */
export function CostLine({ note }: { note?: { text: string; insufficient: boolean } }) {
  if (!note) return null;
  return <p className={styles.costLine} data-short={note.insufficient || undefined}>{note.text}{note.insufficient && <> · <TopUpLink /></>}</p>;
}
