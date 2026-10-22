"use client";
import { useState } from "react";
import type { AuthDiagnostic } from "@/lib/auth/diagnostic-payload";
import styles from "./auth-status.module.css";

export function AuthDiagnosticDetails({ diagnostic }: { diagnostic: AuthDiagnostic }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  return <details className={styles.diagnostic}>
    <summary>故障排查信息</summary>
    <p>诊断编号：{diagnostic.id}<br />发生时间：{new Date(diagnostic.occurred_at).toLocaleString("zh-CN")}</p>
    <button type="button" onClick={async () => {
      try { await navigator.clipboard.writeText(JSON.stringify(diagnostic, null, 2)); setCopied(true); setCopyError(false); }
      catch { setCopyError(true); }
    }}>{copied ? "已复制" : "复制诊断信息"}</button>
    <p aria-live="polite">{copyError ? "复制未完成，请记录上方诊断编号和时间。" : "再次遇到此问题时，可将诊断信息发给我们排查。"}</p>
  </details>;
}
