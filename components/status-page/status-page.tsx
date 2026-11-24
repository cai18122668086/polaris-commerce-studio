import type { ReactNode } from "react";

import styles from "./status-page.module.css";

export const statusPageStyles = styles;

/** 404 和出错页共用的版式 */
export function StatusPage({ code, title, text, reference, children }: { code: string; title: string; text: string; reference?: string; children: ReactNode }) {
  return (
    <main className={styles.page} data-status-page={code}>
      <div className={styles.box}>
        <img className={styles.mark} src="/polaris-mark-ember.svg" alt="" width={44} height={44} />
        <p className={styles.code}>{code}</p>
        <h1 className={styles.title}>{title}</h1>
        <p className={styles.text}>{text}</p>
        {reference && <p className={styles.ref}>错误编号：{reference}</p>}
        <div className={styles.actions}>{children}</div>
      </div>
    </main>
  );
}
