"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef } from "react";
import { apiClient } from "@/lib/api/client";
import { errorMessage, unwrapApiResponse } from "@/lib/api/request";
import styles from "./credit-account.module.css";

export function CreditPurchasePanel({ workspaceId }: { workspaceId: string }) {
  const requestKey = useRef<string | null>(null);
  const catalog = useQuery({
    queryKey: ["credit-packages", workspaceId],
    queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.GET(
      "/api/v1/workspaces/{workspace_id}/credits/packages",
      { params: { path: { workspace_id: workspaceId } }, signal },
    )),
    retry: false,
  });
  const purchase = useMutation({
    mutationFn: async (packageId: string) => {
      requestKey.current ??= crypto.randomUUID();
      return unwrapApiResponse(await apiClient.POST(
        "/api/v1/workspaces/{workspace_id}/credits/purchases",
        {
          params: { path: { workspace_id: workspaceId }, header: { "Idempotency-Key": requestKey.current } },
          body: { package_id: packageId },
        },
      ));
    },
  });
  const currentOrder = useQuery({
    queryKey: ["credit-purchase", workspaceId, purchase.data?.id],
    enabled: Boolean(purchase.data?.id),
    queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.GET(
      "/api/v1/workspaces/{workspace_id}/credits/purchases/{purchase_id}",
      { params: { path: { workspace_id: workspaceId, purchase_id: purchase.data!.id } }, signal },
    )),
    refetchInterval: query => query.state.data?.status === "paid" ? false : 2500,
    retry: false,
  });
  const paid = currentOrder.data?.status === "paid";
  if (!catalog.data?.enabled) return null;
  return <div className={styles.purchase}>
    <h3>补充创作积分</h3>
    {catalog.data.packages.map(pack => <div key={pack.id} className={styles.purchaseRow}>
      <div><strong>{pack.credits.toLocaleString()} 积分</strong><small>可创作约 {Math.floor(pack.credits / 5)} 张普通图片</small></div>
      <b>¥{(pack.amount_fen / 100).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}</b>
      <button type="button" disabled={purchase.isPending || (Boolean(purchase.data) && !paid)} onClick={() => { if (paid) { requestKey.current = null; purchase.reset(); } purchase.mutate(pack.id); }}>
        {purchase.isPending ? "正在创建订单…" : paid ? "继续充值" : purchase.data ? "订单已创建" : "立即充值"}
      </button>
    </div>)}
    {paid && <p role="status">积分已到账。</p>}
    {!paid && purchase.data?.checkout_url && <p><a href={purchase.data.checkout_url} target="_blank" rel="noopener noreferrer">前往收银台付款 →</a><small>付款到账后积分会自动更新。每张图片的积分消耗以创作页面为准。</small></p>}
    {purchase.isError && <p role="alert">{errorMessage(purchase.error)}</p>}
  </div>;
}
