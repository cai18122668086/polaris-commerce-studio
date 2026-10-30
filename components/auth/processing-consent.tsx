"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCurrentAuthUser } from "@/features/auth/api/me";
import { getAuthMode } from "@/lib/auth/config";
import { PROCESSING_NOTICE, processingChoice, processingConsentKey, requestProcessingConsent } from "@/lib/auth/processing-consent";
import { AuthStatus } from "./auth-status";
import styles from "./processing-consent.module.css";

export function ProcessingConsentFields({ hongKong, training, onHongKong, onTraining, disabled = false }: {
  hongKong: boolean; training: boolean; onHongKong: (value: boolean) => void; onTraining: (value: boolean) => void; disabled?: boolean;
}) {
  return <fieldset className={styles.choices} disabled={disabled}>
    <legend>请分别确认以下处理事项</legend>
    <label><input type="checkbox" checked={hongKong} onChange={event => onHongKong(event.target.checked)} /><span>{PROCESSING_NOTICE.crossBorder}</span></label>
    <label><input type="checkbox" checked={training} onChange={event => onTraining(event.target.checked)} /><span>{PROCESSING_NOTICE.aiTraining}</span></label>
    <p>请仅提交你有权处理的素材。处理方式、保存期限与撤回渠道见<Link href="/legal/privacy" target="_blank" rel="noreferrer">隐私政策</Link>。</p>
  </fieldset>;
}

function useProcessingConsent({ refetchOnMount = true }: { refetchOnMount?: boolean } = {}) {
  const user = useCurrentAuthUser();
  const development = getAuthMode() === "development";
  const query = useQuery({ queryKey: processingConsentKey(user.data?.id), queryFn: () => requestProcessingConsent(), enabled: !development && Boolean(user.data?.id), retry: false, retryOnMount: false, refetchOnMount, staleTime: 0 });
  return { query, user, development };
}

export function ProcessingConsentPanel() {
  const headingId = useId();
  const client = useQueryClient();
  // A parent gate owns refresh; mounting its error panel must preserve the
  // failed request until an explicit retry instead of restarting the gate.
  const { query, user, development } = useProcessingConsent({ refetchOnMount: false });
  const [hongKong, setHongKong] = useState(false);
  const [training, setTraining] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [confirmWithdrawal, setConfirmWithdrawal] = useState(false);
  async function submit(withdraw = false) {
    if (!user.data?.id || busy) return;
    setBusy(true); setError(undefined);
    try {
      const result = await requestProcessingConsent(withdraw ? "DELETE" : "POST", withdraw ? undefined : processingChoice(hongKong, training));
      client.setQueryData(processingConsentKey(user.data.id), result);
      setConfirmWithdrawal(false); setHongKong(false); setTraining(false);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "处理授权未能保存，请重试。"); }
    finally { setBusy(false); }
  }
  if (development) return null;
  return <section className={styles.panel} aria-labelledby={headingId}>
    <h2 id={headingId}>图片处理与授权</h2>
    {user.isError || query.isError ? <><p role="alert">授权记录暂时无法读取。</p><button onClick={() => { void user.refetch(); if (user.data) void query.refetch(); }}>重新读取</button></> : user.isPending || query.isPending ? <p role="status">正在读取授权记录…</p> : query.data?.accepted ? <>
      <p>你已确认香港处理与模型训练说明。确认版本：{query.data.policy_version}。</p>
      <p>撤回后停止接收新的上传和创作；已有任务不会因此自动取消，已有结果仍可查看、下载。需要处理已有数据或任务时，请联系隐私客服。</p>
      {confirmWithdrawal ? <div><p>确认撤回以上两项授权？</p><button disabled={busy} onClick={() => void submit(true)}>{busy ? "正在撤回…" : "确认撤回"}</button><button disabled={busy} onClick={() => setConfirmWithdrawal(false)}>保留授权</button></div> : <button onClick={() => setConfirmWithdrawal(true)}>撤回处理授权</button>}
    </> : <>
      <p>开始新的图片创作前，请阅读并分别确认。你仍可查看账户、下载已有作品或联系支持。</p>
      <ProcessingConsentFields hongKong={hongKong} training={training} onHongKong={setHongKong} onTraining={setTraining} disabled={busy} />
      {query.data?.policy_version !== PROCESSING_NOTICE.version ? <p role="alert">处理说明已更新，请刷新页面后重新阅读。</p> : <button disabled={!hongKong || !training || busy} onClick={() => void submit()}>{busy ? "正在保存…" : "确认并继续"}</button>}
    </>}
    {error && <p role="alert">{error}</p>}
  </section>;
}

export function ProcessingConsentGate({ children }: { children: React.ReactNode }) {
  const { query, user, development } = useProcessingConsent();
  if (development) return <>{children}</>;
  if (user.isPending || (!user.isError && query.isPending)) return <AuthStatus busy title="正在读取处理授权" description="请稍候，正在准备创作环境。" />;
  if (user.isError || query.isError || !query.data?.accepted) return <div className={styles.gate}><ProcessingConsentPanel /><p><Link href="/account#settings">账户设置</Link> · <Link href="/jobs">查看已有作品</Link> · <Link href="/">返回首页</Link></p></div>;
  return <>{children}</>;
}

/** Keep the asset list and gallery readable while offering the new-write authorization. */
export function ProcessingConsentNotice() {
  const { query, user, development } = useProcessingConsent();
  if (development || user.isPending || query.isPending || query.data?.accepted) return null;
  return <div className={styles.gate}><ProcessingConsentPanel /></div>;
}
