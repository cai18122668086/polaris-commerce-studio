"use client";

import { useEffect, useRef, useState } from "react";

/** Append a batch without moving the existing scroll position. Filters start anew. */
export function useAutoReveal(total: number, identity: string, rootId?: string, batch = 12) {
  const [page, setPage] = useState({ identity, count: batch });
  const sentinel = useRef<HTMLDivElement>(null);
  const count = Math.min(total, page.identity === identity ? page.count : batch);
  const hasMore = count < total;
  useEffect(() => {
    const target = sentinel.current;
    if (!target || !hasMore || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) {
        observer.disconnect();
        setPage(current => ({ identity, count: Math.min(total, (current.identity === identity ? current.count : batch) + batch) }));
      }
    }, { root: rootId ? document.getElementById(rootId) : null, rootMargin: "180px 0px" });
    observer.observe(target);
    return () => observer.disconnect();
  }, [count, total, identity, hasMore, rootId, batch]);
  return [count, hasMore, sentinel] as const;
}
