"use client";

/* 随内容自动变高的输入框：内容多了自动撑开，最多到 maxHeight，超出再滚动；用户仍可手动拖大。 */

import { useLayoutEffect, useRef, type TextareaHTMLAttributes } from "react";

export function AutoGrowTextarea({ maxHeight = 360, style, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { maxHeight?: number }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    const border = el.offsetHeight - el.clientHeight;
    el.style.height = `${Math.min(el.scrollHeight + border, maxHeight)}px`;
    el.style.overflowY = el.scrollHeight + border > maxHeight ? "auto" : "hidden";
  }, [props.value, maxHeight]);
  return <textarea ref={ref} style={style} {...props} />;
}
