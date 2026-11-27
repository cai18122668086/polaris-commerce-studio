"use client";

import type { ReactNode } from "react";
import { useFreeEdits } from "@/features/assets/api/assets";
import { CreditCostHint } from "@/features/billing/components/credit-account";

/** Price of the next edit of an image: free while its 3 free edits last. */
export function FreeEditCost({ workspaceId, assetId, fallback }: { workspaceId?: string; assetId?: string; fallback?: ReactNode }) {
  const allowance = useFreeEdits(workspaceId, assetId);
  const data = allowance.data;
  if (data?.eligible && data.remaining > 0) return <strong>本次免费 · 这张图还剩 {data.remaining}/{data.limit} 次免费修改</strong>;
  return <>{data?.eligible ? <span>{data.limit} 次免费修改已用完 · </span> : null}<CreditCostHint jobType="local_edit" count={1} fallback={fallback} /></>;
}

/** Copy for the short price label on a regenerate button. */
export function useNextEditIsFree(workspaceId?: string, assetId?: string): boolean {
  const allowance = useFreeEdits(workspaceId, assetId);
  return Boolean(allowance.data?.eligible && allowance.data.remaining > 0);
}
