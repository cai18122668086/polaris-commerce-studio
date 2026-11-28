"use client";

import { useState } from "react";
import { mediaUrl } from "@/lib/api/base-url";

/**
 * A benchmark cover from our own API (the site's CSP blocks platform CDNs, and
 * their links expire). Falls back to a plain label when there is no picture.
 */
export function coverSrc(workspaceId: string, pageId: string | undefined, platformId: string) {
  return pageId ? mediaUrl(`/api/v1/video-studio/workspaces/${workspaceId}/benchmark-covers/${pageId}/${platformId}`) : undefined;
}

export function BenchmarkCover({ src, label, className, emptyClassName }: { src?: string; label: string; className?: string; emptyClassName?: string }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return <span className={emptyClassName}>{label}</span>;
  return <img src={src} alt="" loading="lazy" className={className} onError={() => setFailed(true)} />;
}
