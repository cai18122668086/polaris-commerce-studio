"use client";

import Link from "next/link";
import { useEffect } from "react";

import { StatusPage, statusPageStyles as styles } from "@/components/status-page/status-page";

export default function RouteError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => { console.error(error); }, [error]);
  return (
    <StatusPage code="出错了" title="页面暂时没能打开" text="可能是网络波动或服务繁忙，请稍后重试。" reference={error.digest}>
      <button type="button" className={`${styles.btn} ${styles.primary}`} onClick={() => reset()}>重试</button>
      <Link className={styles.btn} href="/">返回首页</Link>
    </StatusPage>
  );
}
