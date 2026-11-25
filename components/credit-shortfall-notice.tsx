"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";
import { Coins, X } from "lucide-react";
import { creditShortfallSnapshot, dismissCreditShortfall, noCreditShortfall, subscribeCreditShortfall } from "@/lib/billing/insufficient-credits";

/** Global 402 follow-up: the inline error says what happened, this gives the way out. */
export function CreditShortfallNotice() {
  const shortfall = useSyncExternalStore(subscribeCreditShortfall, creditShortfallSnapshot, noCreditShortfall);
  const pathname = usePathname();
  if (!shortfall) return null;
  const detail = typeof shortfall.required === "number"
    ? `本次需要 ${shortfall.required} 积分${typeof shortfall.available === "number" ? `，当前可用 ${shortfall.available} 积分` : ""}。`
    : "当前可用积分不足以完成本次生成。";
  return <div className="credit-shortfall" role="alert">
    <Coins size={17} aria-hidden="true" />
    <p><strong>积分不足，未提交生成</strong><span>{detail}充值后回到本页即可继续，已填写的内容会保留。</span></p>
    <Link className="primary-button" href={`/account?returnTo=${encodeURIComponent(pathname)}#membership`} onClick={dismissCreditShortfall}>充值积分</Link>
    <button type="button" className="icon-button" aria-label="关闭积分提示" onClick={dismissCreditShortfall}><X size={16} /></button>
  </div>;
}
