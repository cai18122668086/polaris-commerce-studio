"use client";

import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import { editingMessage } from "@/features/video-studio/editing-presentation";
import styles from "./editing-workspace.module.css";

type ImageTarget = components["schemas"]["EditingImageTarget"];
type ImageEdit = components["schemas"]["NativeImageEdit"];
type Material = components["schemas"]["EditingMaterialResponse"];
const projectPath = "/api/v1/video-studio/workspaces/{workspace_id}/projects/{project_id}" as const;
const materialsPath = `${projectPath}/editing-materials` as const;

export function EditingImageEdits({ workspaceId, projectId, planId, selected, sourceOnly, disabled, onChange }: {
  workspaceId: string; projectId: string; planId: string; selected: ImageEdit[];
  sourceOnly: string[]; disabled: boolean; onChange: (edits: ImageEdit[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [targets, setTargets] = useState<ImageTarget[]>();
  const [rows, setRows] = useState<Material[]>([]);
  const [offset, setOffset] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]);
    const path = { workspace_id: workspaceId, project_id: projectId };
    const load = async () => {
      try {
        const [options, materials] = await Promise.all([
          apiClient.GET(`${projectPath}/editing-native-plans/{plan_id}/image-targets`, {
            params: { path: { ...path, plan_id: planId } }, signal,
          }),
          apiClient.GET(materialsPath, { params: { path }, signal }),
        ]);
        if (controller.signal.aborted) return;
        const nextTargets = unwrapApiResponse(options);
        const data = unwrapApiResponse(materials);
        setTargets(nextTargets);
        setRows(previous => [...data.items, ...previous.filter(item => !data.items.some(row => row.id === item.id))]);
        setOffset(data.next_offset);
        setError("");
      } catch {
        if (!controller.signal.aborted) setError("暂时无法读取配图，请合上后重新展开。");
      }
    };
    void load();
    return () => controller.abort();
  }, [open, workspaceId, projectId, planId]);

  const more = async () => {
    if (offset === null) return;
    setBusy(true); setError("");
    try {
      const data = unwrapApiResponse(await apiClient.GET(materialsPath, {
        params: { path: { workspace_id: workspaceId, project_id: projectId }, query: { offset } },
        signal: AbortSignal.timeout(12000),
      }));
      setRows(previous => [...previous, ...data.items.filter(row => !previous.some(item => item.id === row.id))]);
      setOffset(data.next_offset);
    } catch { setError("暂时无法读取更多素材。"); }
    finally { setBusy(false); }
  };

  const images = rows.filter(row => row.kind === "image");
  return <details onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>替换配图</summary>
    <div className={styles.materials}>
      <p className={styles.note}>从本期素材选图。可先在「本期补充素材」上传实拍或导入创意图。只替换图片，沿用原口播词点和卡片动画。</p>
      {open && !targets && !error && <p role="status">正在读取配图位置和本期素材…</p>}
      {targets?.length === 0 && <p>本编排暂无可替换的配图。</p>}
      {targets?.map((target, index) => {
        const label = `配图 ${index + 1}`;
        const belongs = (edit: ImageEdit) => edit.beat_id === target.beat_id && edit.path === target.path;
        const active = selected.find(belongs);
        const original = images.find(row => row.id === target.current_material_id);
        const current = active ? images.find(row => row.id === active.material_id) : original;
        const choices = images.filter(row => row.id !== target.current_material_id && row.sha256 !== original?.sha256);
        return <div key={target.beat_id + target.path} className={styles.materialList}>
          <label>{label}
            <select aria-label={label} value={active?.material_id ?? ""} disabled={disabled || sourceOnly.includes(target.beat_id)}
              onChange={event => {
                const replacement = choices.find(row => row.id === event.target.value);
                const edits = selected.filter(edit => !belongs(edit));
                if (replacement) edits.push({
                  beat_id: target.beat_id, path: target.path,
                  material_id: replacement.id, sha256: replacement.sha256,
                });
                onChange(edits);
              }}>
              <option value="">沿用原图{original && ` · ${original.label}`}</option>
              {choices.map(row => <option key={row.id} value={row.id}>{row.label}</option>)}
            </select>
          </label>
          {target.requires_transparency && <p className={styles.note}>此图槽需要含透明像素的图片。</p>}
          {current && <a href={current.url} target="_blank" rel="noreferrer">查看「{current.label}」原件</a>}
        </div>;
      })}
      {offset !== null && <button type="button" disabled={busy || disabled} onClick={() => void more()}>加载更多素材</button>}
      {error && <p className={styles.error} role="alert">{editingMessage(error, "暂时无法读取配图选项，请稍后重试。")}</p>}
    </div>
  </details>;
}
