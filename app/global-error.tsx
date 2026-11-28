"use client";

import { useEffect } from "react";

import { StatusPage, statusPageStyles as styles } from "@/components/status-page/status-page";

/* 根布局本身出错时的兜底页：不经过全站布局和样式，需要自己输出 html / body */
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => { console.error(error); }, [error]);
  return (
    <html lang="zh-CN">
      <head><title>出错了｜极光商绘</title><meta name="robots" content="noindex" /></head>
      <body style={{ margin: 0, background: "#0b0b0b" }}>
        <StatusPage code="出错了" title="网站暂时没能打开" text="可能是网络波动或服务繁忙，请稍后重试。" reference={error.digest}>
          <button type="button" className={`${styles.btn} ${styles.primary}`} onClick={() => reset()}>重试</button>
          {/* 根布局已失效，用整页跳转回首页，不走客户端路由 */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a className={styles.btn} href="/">返回首页</a>
        </StatusPage>
      </body>
    </html>
  );
}
