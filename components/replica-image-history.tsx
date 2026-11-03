"use client";

import { useEffect, useRef, useState } from "react";
import { Check, LoaderCircle, Paintbrush2, X } from "lucide-react";
import { useAssetAccessUrl } from "@/features/assets/api/assets";
import { useReplicaImageHistory, useSelectReplicaImage } from "@/features/jobs/api/jobs";
import { errorMessage } from "@/lib/api/request";
import { useBodyScrollLock } from "@/lib/hooks/use-body-scroll-lock";
import styles from "./replica-image-history.module.css";

function Thumbnail({ workspaceId, assetId }: { workspaceId: string; assetId: string }) {
  const access = useAssetAccessUrl(workspaceId, assetId, "thumbnail");
  return access.data?.url ? <img src={access.data.url} alt="" /> : <span className={styles.placeholder} />;
}

export function ReplicaImageHistoryDialog({ workspaceId, jobId, itemId, title, onClose, onEdit }: {
  workspaceId: string; jobId: string; itemId: string; title: string;
  onClose: () => void; onEdit: (assetId: string, localEditJobId?: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const history = useReplicaImageHistory(workspaceId, jobId, itemId);
  const select = useSelectReplicaImage(workspaceId);
  const [selected, setSelected] = useState<string>();
  const [error, setError] = useState<string>();
  const data = history.data;
  const selectedId = selected ?? data?.current_local_edit_job_id ?? "original";
  const record = data?.records.find(row => row.job_id === selectedId);
  const assetId = selectedId === "original" ? data?.original_asset_id
    : record?.result_asset_id ?? record?.source_asset_id ?? (selectedId === data?.current_local_edit_job_id ? data.current_asset_id : undefined);
  const access = useAssetAccessUrl(workspaceId, assetId);
  const isCurrent = selectedId === (data?.current_local_edit_job_id ?? "original");
  const canSelect = Boolean(data?.allowed_actions.includes("select_replica_image")) && (selectedId === "original" || record?.status === "completed");
  useBodyScrollLock(true);
  useEffect(() => { dialog.current?.showModal(); }, []);
  const choose = async () => {
    if (!data || select.isPending) return;
    setError(undefined);
    try {
      await select.mutateAsync({ jobId, itemId, expectedAssetId: data.current_asset_id,
        localEditJobId: selectedId === "original" ? null : selectedId, allowedActions: data.allowed_actions });
    } catch (caught) {
      setError(errorMessage(caught));
      void history.refetch();
    }
  };
  return <dialog ref={dialog} className={styles.dialog} aria-labelledby="replica-history-title"
    onCancel={event => { event.preventDefault(); if (!select.isPending) onClose(); }}
    onClick={event => { if (event.target === event.currentTarget && !select.isPending) onClose(); }}>
    <header className={styles.header}><div><h2 id="replica-history-title">修改记录</h2><p>{title}</p></div>
      <button type="button" onClick={onClose} disabled={select.isPending} aria-label="关闭修改记录"><X size={20} /></button>
    </header>
    {history.isPending ? <div className={styles.loading}><LoaderCircle className="spin" size={24} />正在加载记录…</div>
      : history.error ? <div className={styles.loading} role="alert"><p>{errorMessage(history.error)}</p><button type="button" onClick={() => void history.refetch()}>重新加载</button></div>
        : data && <div className={styles.body}>
          <div className={styles.preview}>{access.data?.url ? <img src={access.data.url} alt="复刻图片历史预览" /> : access.error ? <p role="alert">图片暂不可用</p> : <LoaderCircle className="spin" size={24} />}</div>
          <aside className={styles.sidebar}>
            <div className={styles.versions} role="group" aria-label="图片修改版本">
              <button type="button" className={styles.version} aria-pressed={selectedId === "original"} onClick={() => setSelected("original")} disabled={select.isPending}>
                <Thumbnail workspaceId={workspaceId} assetId={data.original_asset_id} /><span><strong>原版</strong><small>{!data.current_local_edit_job_id ? "当前图片" : "一键复刻生成"}</small></span>
              </button>
              {data.records.map((row, index) => <button key={row.job_id} type="button" className={styles.version} aria-pressed={selectedId === row.job_id} onClick={() => setSelected(row.job_id)} disabled={select.isPending}>
                <Thumbnail workspaceId={workspaceId} assetId={row.result_asset_id ?? row.source_asset_id} />
                <span><strong>修改 {data.records.length - index}<span className={styles.status}>{row.is_current ? "当前" : row.status === "completed" ? "已保存" : row.status === "awaiting_final_review" ? "待确认" : ["failed", "cancelled"].includes(row.status) ? "未完成" : "生成中"}</span></strong>
                  <small className={styles.instruction}>{row.instruction}</small><time dateTime={row.created_at}>{new Date(row.created_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</time></span>
              </button>)}
            </div>
            <div className={styles.actions}>
              {canSelect && !isCurrent && <button type="button" className={styles.primary} disabled={select.isPending || !access.data?.url} onClick={() => void choose()}>{select.isPending ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />}设为当前图片</button>}
              {isCurrent && assetId && data.allowed_actions.includes("select_replica_image") && <button type="button" className={styles.primary} onClick={() => onEdit(assetId)}><Paintbrush2 size={16} />继续修改</button>}
              {record && <button type="button" className={styles.detail} disabled={select.isPending} onClick={() => onEdit(record.source_asset_id, record.job_id)}>打开这次修改</button>}
              {error && <p className={styles.error} role="alert">{error}</p>}
            </div>
          </aside>
        </div>}
  </dialog>;
}
