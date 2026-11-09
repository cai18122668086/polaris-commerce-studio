"use client";

import { useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import styles from "./editing-workspace.module.css";

type Material = components["schemas"]["EditingMaterialResponse"];
const path = "/api/v1/video-studio/workspaces/{workspace_id}/projects/{project_id}/editing-materials" as const;

export function EditingProjectMaterials({ workspaceId, projectId, selected, onSelect }: {
  workspaceId: string;
  projectId: string;
  selected: string[];
  onSelect: (ids: string[]) => void;
}) {
  const [rows, setRows] = useState<Material[]>([]);
  const [offset, setOffset] = useState<number | null>(null);
  const [file, setFile] = useState<File>();
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const intent = useRef<{ file: File; label: string; description: string; id: string } | undefined>(undefined);

  useEffect(() => {
    const controller = new AbortController();
    void apiClient.GET(path, {
      params: { path: { workspace_id: workspaceId, project_id: projectId } }, signal: controller.signal,
    }).then(result => {
      const data = unwrapApiResponse(result);
      if (!controller.signal.aborted) { setRows(data.items); setOffset(data.next_offset); }
    }).catch(() => { if (!controller.signal.aborted) setError("暂时无法读取本期素材。"); });
    return () => controller.abort();
  }, [workspaceId, projectId]);

  const upload = async () => {
    if (!file || !label.trim() || !description.trim()) return;
    setBusy(true); setError("");
    try {
      if (intent.current?.file !== file || intent.current.label !== label || intent.current.description !== description) {
        intent.current = { file, label, description, id: crypto.randomUUID() };
      }
      const form = new FormData();
      form.append("file", file); form.append("request_id", intent.current.id);
      form.append("label", label); form.append("description", description);
      const material = unwrapApiResponse(await apiClient.POST(path, {
        params: { path: { workspace_id: workspaceId, project_id: projectId } }, signal: AbortSignal.timeout(600000),
        body: {} as never, bodySerializer: () => form,
      }));
      setRows(previous => [material, ...previous.filter(row => row.id !== material.id)]);
      intent.current = undefined; setFile(undefined); setLabel(""); setDescription("");
      if (fileInput.current) fileInput.current.value = "";
    } catch (caught) { setError(caught instanceof Error ? caught.message : "素材保存暂未确认，可重试同一请求。"); }
    finally { setBusy(false); }
  };

  const more = async () => {
    if (offset === null) return;
    setBusy(true); setError("");
    try {
      const data = unwrapApiResponse(await apiClient.GET(path, {
        params: { path: { workspace_id: workspaceId, project_id: projectId }, query: { offset } }, signal: AbortSignal.timeout(12000),
      }));
      setRows(previous => [...previous, ...data.items.filter(row => !previous.some(item => item.id === row.id))]);
      setOffset(data.next_offset);
    } catch { setError("暂时无法读取更多素材。"); }
    finally { setBusy(false); }
  };

  return <details><summary>本期补充素材</summary>
    <section aria-label="本期补充素材" className={styles.materials}>
      <p className={styles.note}>上传当前项目可用的实拍或图片。勾选的素材说明和身份摘要会进入本次规划请求，原件由渲染时读取。画面说明和商品事实待核对。</p>
      <label>素材文件<input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm" disabled={busy} onChange={event => setFile(event.target.files?.[0])} /></label>
      <label>素材名称<input value={label} maxLength={120} disabled={busy} onChange={event => setLabel(event.target.value)} /></label>
      <label>实际画面说明<textarea value={description} maxLength={400} disabled={busy} onChange={event => setDescription(event.target.value)} /></label>
      <button type="button" onClick={() => void upload()} disabled={busy || !file || !label.trim() || !description.trim()}>保存补充素材</button>
      {error && <p role="alert" className={styles.error}>{error}</p>}
      {!!rows.length && <p role="status">本次规划已选 {selected.length} / 24 项</p>}
      <ul className={styles.materialList}>{rows.map(row => <li key={row.id} data-material-id={row.id}>
        <label className={styles.reviewCheck}><input type="checkbox" checked={selected.includes(row.id)} disabled={!selected.includes(row.id) && selected.length >= 24} onChange={event => onSelect(event.target.checked ? [...selected, row.id] : selected.filter(id => id !== row.id))} />{row.label}</label>
        <p className={styles.note}>{row.description} · {row.width} × {row.height}{row.duration_ms !== null && ` · ${row.duration_ms / 1000} 秒`}</p>
        <a href={row.url} target="_blank" rel="noreferrer">查看素材原件</a>
      </li>)}</ul>
      {offset !== null && <button type="button" disabled={busy} onClick={() => void more()}>加载更多素材</button>}
    </section>
  </details>;
}
