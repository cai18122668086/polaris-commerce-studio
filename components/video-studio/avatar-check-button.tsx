"use client";

import { useState } from "react";

/**
 * 「结果待确认」的形象任务：只查询，不重新提交、不调 /resume（B7）。
 * onNotice 给了就交给页面的提示条，否则在按钮下方显示说明。
 */
export function AvatarCheckButton({ jobId, check, checking, className, noticeClassName, onNotice }: {
  jobId: string;
  check: (id: string) => Promise<string | null>;
  checking: boolean;
  className?: string;
  noticeClassName?: string;
  onNotice?: (text: string, tone: "info" | "error") => void;
}) {
  const [notice, setNotice] = useState("");
  const show = (text: string, tone: "info" | "error") => (onNotice ? onNotice(text, tone) : setNotice(text));
  const run = async () => {
    try {
      const text = await check(jobId);
      show(text || "已重新核对，正在继续查询进度。", "info");
    } catch {
      show("暂时查询不到结果，请稍后再试。不会重新生成，也不会重复扣积分。", "error");
    }
  };
  return <>
    <button type="button" className={className} disabled={checking} onClick={() => void run()}>{checking ? "正在查询…" : "查询结果"}</button>
    {!onNotice && notice && <small className={noticeClassName} role="status">{notice}</small>}
  </>;
}
