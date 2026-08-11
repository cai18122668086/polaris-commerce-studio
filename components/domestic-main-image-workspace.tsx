"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  GripVertical,
  ImagePlus,
  LoaderCircle,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { WorkspaceHeader } from "@/components/workspace-header";
import { useUploadAsset } from "@/features/assets/api/assets";
import {
  type SourceRole,
  useAuthorizeDomesticMainImageTask,
  useCreateDomesticMainImageTask,
  useDomesticMainImageTask,
} from "@/features/domestic-main-image/api/tasks";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import type { Asset } from "@/lib/api/types";
import { IMAGE_UPLOAD_ACCEPT } from "@/lib/image-upload";

import styles from "./domestic-main-image-workspace.module.css";

type Source = { asset: Asset; previewUrl: string; role: SourceRole };

const roleLabels: Record<SourceRole, string> = {
  primary: "主要身份图",
  detail: "细节证据",
  back: "背面证据",
  package: "包装证据",
  structure: "结构证据",
};

function splitFacts(value: string) {
  return value
    .split(/[；;\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function DomesticMainImageWorkspace() {
  const fileInput = useRef<HTMLInputElement>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [productName, setProductName] = useState("");
  const [category, setCategory] = useState("");
  const [productInformation, setProductInformation] = useState("");
  const [sellingPoints, setSellingPoints] = useState("");
  const [taskId, setTaskId] = useState<string>();
  const [localError, setLocalError] = useState<string>();
  const { workspace } = useWorkspace();
  const upload = useUploadAsset(workspace?.id);
  const createTask = useCreateDomesticMainImageTask(workspace?.id);
  const authorize = useAuthorizeDomesticMainImageTask(workspace?.id);
  const taskQuery = useDomesticMainImageTask(workspace?.id, taskId);
  const task = taskQuery.data ?? createTask.data ?? authorize.data;

  const sourcesRef = useRef(sources);
  useEffect(() => {
    sourcesRef.current = sources;
  }, [sources]);
  useEffect(
    () => () => {
      sourcesRef.current.forEach((source) => URL.revokeObjectURL(source.previewUrl));
    },
    [],
  );

  async function addFiles(files: File[]) {
    setLocalError(undefined);
    for (const file of files.slice(0, 12 - sources.length)) {
      const previewUrl = URL.createObjectURL(file);
      try {
        const asset = await upload.mutateAsync({ file, mediaKind: "image" });
        setSources((current) => [
          ...current,
          { asset, previewUrl, role: current.length === 0 ? "primary" : "detail" },
        ]);
      } catch (error) {
        URL.revokeObjectURL(previewUrl);
        setLocalError(error instanceof Error ? error.message : "图片上传失败。");
      }
    }
  }

  function removeSource(assetId: string) {
    setSources((current) => {
      const removed = current.find((source) => source.asset.id === assetId);
      if (removed) URL.revokeObjectURL(removed.previewUrl);
      const next = current.filter((source) => source.asset.id !== assetId);
      if (removed?.role === "primary" && next.length > 0) next[0] = { ...next[0], role: "primary" };
      return next;
    });
  }

  function setRole(assetId: string, role: SourceRole) {
    setSources((current) =>
      current.map((source) => {
        if (role === "primary" && source.role === "primary") {
          return { ...source, role: "detail" };
        }
        return source.asset.id === assetId ? { ...source, role } : source;
      }),
    );
  }

  async function create() {
    if (!sources.length || !productName.trim() || !category.trim() || !productInformation.trim()) return;
    const created = await createTask.mutateAsync({
      product_name: productName.trim(),
      category: category.trim(),
      product_information: productInformation.trim(),
      verified_selling_points: splitFacts(sellingPoints),
      sources: sources.map((source) => ({ asset_id: source.asset.id, role: source.role })),
    });
    setTaskId(created.id);
  }

  const error = localError ?? createTask.error?.message ?? authorize.error?.message ?? taskQuery.error?.message;
  const readyToCreate = Boolean(
    workspace && sources.length && productName.trim() && category.trim() && productInformation.trim(),
  );

  return (
    <AppShell flush>
      <div className={styles.page}>
        <WorkspaceHeader
          eyebrow="国内电商 · 原版 Skill 驱动"
          title="搜索主图 + 五张轮播图"
          description="商品身份、六页职责、返修预算与下一合法动作全部来自 Skill session。"
          meta={<span className="autosave-state"><ShieldCheck size={15} />真实 Provider 默认关闭</span>}
        />

        <section className={styles.card}>
          <div className={styles.heading}><span>1</span><div><h2>同一商品原图</h2><p>拖入多角度证据，并明确每张图的身份角色。</p></div></div>
          <div className={styles.uploadGrid}>
            {sources.map((source, index) => (
              <article className={styles.source} key={source.asset.id}>
                <img src={source.previewUrl} alt={`商品证据 ${index + 1}`} />
                <div><GripVertical size={14} /><select value={source.role} onChange={(event) => setRole(source.asset.id, event.target.value as SourceRole)} aria-label={`第 ${index + 1} 张素材角色`}>
                  {Object.entries(roleLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select></div>
                <button aria-label={`移除第 ${index + 1} 张图片`} onClick={() => removeSource(source.asset.id)}><X size={14} /></button>
              </article>
            ))}
            {sources.length < 12 && <button className={styles.uploadButton} onClick={() => fileInput.current?.click()} disabled={!workspace || upload.isPending}>{upload.isPending ? <LoaderCircle className="spin" /> : <ImagePlus />}<strong>{upload.isPending ? "上传中" : "添加原图"}</strong><small>最多 12 张</small></button>}
            <input ref={fileInput} className="visually-hidden" type="file" multiple accept={IMAGE_UPLOAD_ACCEPT} onChange={(event) => { const files = Array.from(event.currentTarget.files ?? []); event.currentTarget.value = ""; void addFiles(files); }} />
          </div>
        </section>

        <section className={styles.card}>
          <div className={styles.heading}><span>2</span><div><h2>商品信息</h2><p>你主动提供的事实进入 USER_PROVIDED_DISPLAY_FACT 真相池。</p></div></div>
          <div className={styles.formGrid}>
            <label><span>商品名称 *</span><input value={productName} onChange={(event) => setProductName(event.target.value)} placeholder="例如：桌面循环扇" disabled={Boolean(taskId)} /></label>
            <label><span>商品类目 *</span><input value={category} onChange={(event) => setCategory(event.target.value)} placeholder="例如：小家电 / 风扇" disabled={Boolean(taskId)} /></label>
            <label className={styles.full}><span>商品完整信息 *</span><textarea value={productInformation} onChange={(event) => setProductInformation(event.target.value)} placeholder="规格、结构、材质、适用人群、服务与必须保持的真实信息" disabled={Boolean(taskId)} /></label>
            <label className={styles.full}><span>已验证卖点</span><textarea value={sellingPoints} onChange={(event) => setSellingPoints(event.target.value)} placeholder="用分号或换行分隔；不会要求每条都上画面" disabled={Boolean(taskId)} /></label>
          </div>
        </section>

        {error && <div className={styles.error}><AlertCircle /><div><strong>请求未完成</strong><p>{error}</p></div></div>}

        <section className={styles.card}>
          <div className={styles.heading}><span>3</span><div><h2>六图规划</h2><p>{task?.campaign_style_summary ?? "完成商品身份像素识别后，原版 Skill 将生成六页精简规划。"}</p></div></div>
          {!task && <div className={styles.empty}>尚未创建任务。上传素材并填写商品信息后生成规划。</div>}
          {task?.skill_state === "AWAITING_IDENTITY" && <div className={styles.notice}><LoaderCircle className="spin" /><div><strong>等待商品身份像素识别</strong><p>任务和原图已持久化。身份审核服务未配置时会停在这里，不会用文件名、哈希或用户文字冒充像素判断。</p></div></div>}
          {task && task.plan.length > 0 && <div className={styles.planTable}><div className={styles.planHeader}><span>页码/职责</span><span>主卖点 / 辅助卖点</span><span>画面证明</span><span>构图与主体</span><span>阅读路径 / 文字层级</span><span>不重复理由</span><span>商业闭合</span></div>{task.plan.map((row) => <article key={row.page_index}><span><b>{row.page_index + 1}</b>{row.page_role}</span><span><strong>{row.main_selling_point}</strong><small>{row.supporting_selling_points.join("；") || "无"}</small></span><span>{row.visual_proof}</span><span>{row.composition_and_subject}</span><span>{row.reading_path_and_type_hierarchy}</span><span>{row.non_repetition_reason}</span><span>{row.commercial_closure}</span></article>)}</div>}
        </section>

        {task && <section className={styles.card}>
          <div className={styles.heading}><span>4</span><div><h2>六图任务</h2><p>候选图保存后会立即出现并标记“审核中”；审核故障不会让图片消失。</p></div><em>{task.skill_state}</em></div>
          <div className={styles.pageGrid}>{Array.from({ length: 6 }, (_, index) => <article key={index}><div><span>{index === 0 ? "搜索获客主图" : `轮播图 ${index}`}</span><small>{index === 0 ? "唯一搜索入口" : "等待 Skill 顺序推进"}</small></div><i>{task.generation_request_ready && index === 0 ? "等待已批准 Provider" : "等待生成"}</i></article>)}</div>
          {task.generation_request_ready && <div className={styles.contract}><CheckCircle2 /><div><strong>首个 generate-next 合同已原样保存</strong><p>Prompt SHA-256：{task.generation_prompt_sha256}</p><p>引用角色：{task.reference_roles.join(" → ")}；编辑目标：{task.edit_target_role ?? "无"}</p></div></div>}
        </section>}

        <footer className={styles.footer}>
          <div><strong>Skill {task?.skill_version ?? "0.1.17"}</strong><span>{task ? `revision ${task.revision} · ${task.skill_state}` : "零费用规划阶段"}</span></div>
          {!taskId ? <button className="primary-button" disabled={!readyToCreate || createTask.isPending} onClick={() => void create()}>{createTask.isPending ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}生成六图规划</button> : task?.skill_state === "AWAITING_AUTHORIZATION" ? <button className="primary-button" disabled={authorize.isPending} onClick={() => void authorize.mutateAsync({ taskId, revision: task.revision })}>{authorize.isPending ? <LoaderCircle className="spin" size={17} /> : <CheckCircle2 size={17} />}一次确认六图规划</button> : <button className="primary-button" disabled><LoaderCircle className={task && !["AWAITING_USER_FINAL_REVIEW", "FINALIZED"].includes(task.skill_state) ? "spin" : ""} size={17} />{task?.skill_state === "AWAITING_IDENTITY" ? "等待身份审核" : task?.generation_request_ready ? "等待 Provider 能力批准" : "按 Skill 状态推进"}</button>}
        </footer>
      </div>
    </AppShell>
  );
}
