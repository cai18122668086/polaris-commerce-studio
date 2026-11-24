"use client";

import { useRouter } from "next/navigation";

/** 有上一页就返回，没有就去首页 */
export function BackButton({ className }: { className?: string }) {
  const router = useRouter();
  return (
    <button type="button" className={className} onClick={() => { if (window.history.length > 1) router.back(); else router.push("/"); }}>
      返回上一页
    </button>
  );
}
