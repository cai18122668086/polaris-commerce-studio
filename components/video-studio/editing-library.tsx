"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import styles from "./editing-library.module.css";

type Note = components["schemas"]["EditingLibraryNoteResponse"];
type NotePage = components["schemas"]["EditingLibraryNotesResponse"];
type TargetKind = Note["target_kind"];
type Group = { id: string; name: string; kind: string; purpose: string; primary_function: string; branch: string; runtime_validation: string; contract: string | null };
type LocalDependencyState = "not_registered" | "file_missing" | "identity_mismatch" | "verified";
type Asset = { id: string; kind: string; display_name: string; duration_seconds?: number; availability: string; local_dependency_state?: LocalDependencyState; audio_preview_supported: boolean; source?: string; purpose?: string; faces?: { family?: string; full_name?: string }[] };
type Summary = { groups: number; bundled_assets: number; external_references: number; runtime: Record<string, number>; visual_accepted: number };
type Catalog = { total: number; groups: Group[]; next_offset: number | null; summary: Summary };
type ResourcePage = { resources: Asset[]; total: number; next_offset: number | null };
type OriginalStartupAsset = {
  native_path_pattern: string;
  expected_count: number;
  bundled_count: number;
  verified_bundled_count: number;
  verified_supplement_count: number;
  missing_paths: string[];
  usage: "drawn" | "without_presenter" | "without_item_image" | "shared_startup";
  supplement_registry_invalid: boolean;
  indexed_external_ids: string[];
};
type Detail = {
  template_dependencies: { id: string; kind: string; display_name: string; binding_scope: string; original_rights?: string; local_dependency_state?: LocalDependencyState }[];
  runtime_evidence: { id: string; runtime_validation: string; recorded_at: string; native_branch?: string }[];
  original_input_variants?: { id: string; template_sha256: string; has_encoded_sample: boolean;
    dependency_fonts: { id: string; display_name: string; local_dependency_state: LocalDependencyState }[] }[];
  original_startup_assets?: OriginalStartupAsset[];
  contract_status: string;
  parameter_contract: {
    native_profile?: string | null;
    classic_authoring_status?: string;
    website_sidecar_scope?: string;
    native_branches?: Record<string, { branch_paths: string[] }>;
    media_clock_profile?: { project_scene_clip_paths?: string[] } | null;
  };
};
type Target = { kind: TargetKind; id: string; name: string };
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
const notePath = `${root}/projects/{project_id}/editing-library-notes` as const;
const runtimeLabel: Record<string, string> = { unverified: "待实际验证", sample_rendered: "有编码样本 · 未验收", sample_failed: "有失败样本", mixed_samples: "样本结果不一" };
const kindLabel: Record<string, string> = { font: "字体", sfx: "音效", "sfx-processed": "处理后的音效", music: "背景音乐", image: "插画", geometry: "几何轮廓", media: "历史素材引用", model: "模型依赖" };
const dependencyLabel: Record<string, string> = {
  current_project_media: "需绑定本片真实素材",
  engine_font_reference: "原入口引用，按运行分支核对",
  selectable_original_font: "可显式选择原包字体",
};
const localDependencyLabel: Record<LocalDependencyState, string> = {
  not_registered: "本机未登记原件",
  file_missing: "已登记文件缺失",
  identity_mismatch: "已登记文件与原件摘要不符",
  verified: "本机原件摘要已核验",
};
const startupUsageLabel: Record<OriginalStartupAsset["usage"], string> = {
  drawn: "本组画面需要",
  without_presenter: "未绑定本片人物时使用",
  without_item_image: "相应图片槽留空时使用",
  shared_startup: "共用入口预加载",
};
const choiceLabel = { consider: "优先考虑", avoid: "本项目暂不选用", clear: "清除倾向" };
const targetKey = (kind: TargetKind, id: string) => `${kind}:${id}`;

export function EditingLibrary({ workspaceId, projectId, saved }: { workspaceId: string; projectId: string; saved: boolean }) {
  const [catalog, setCatalog] = useState<Catalog>();
  const [tab, setTab] = useState<"groups" | "resources" | "notes">("groups");
  const [search, setSearch] = useState("");
  const [groupKind, setGroupKind] = useState("");
  const [functionFilter, setFunctionFilter] = useState("");
  const [detailId, setDetailId] = useState("");
  const [detail, setDetail] = useState<Detail>();
  const [source, setSource] = useState<"bundled" | "external">("bundled");
  const [assetKind, setAssetKind] = useState("");
  const [resourceDraft, setResourceDraft] = useState("");
  const [resourceSearch, setResourceSearch] = useState("");
  const [resourcePage, setResourcePage] = useState<ResourcePage>();
  const [resourceOffset, setResourceOffset] = useState(0);
  const [resourceLoading, setResourceLoading] = useState(false);
  const [resourceReload, setResourceReload] = useState(0);
  const [audioId, setAudioId] = useState("");
  const [notes, setNotes] = useState<Note[]>([]);
  const [target, setTarget] = useState<Target>();
  const [choice, setChoice] = useState<Note["choice"]>("consider");
  const [reason, setReason] = useState("");
  const [history, setHistory] = useState<Note[]>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const pending = useRef<{ key: string; id: string } | undefined>(undefined);
  const detailRequest = useRef("");
  const noteMap = useMemo(() => new Map(notes.map(n => [targetKey(n.target_kind, n.target_id), n])), [notes]);
  const loadNotes = useCallback(async () => {
    if (!saved) return [];
    const all: Note[] = [];
    let offset: number | null = 0;
    do {
      const page: NotePage = unwrapApiResponse(await apiClient.GET(notePath, { params: { path: { workspace_id: workspaceId, project_id: projectId }, query: { offset, limit: 200 } }, signal: AbortSignal.timeout(12000) }));
      all.push(...page.items);
      if (page.next_offset !== null && page.next_offset <= offset) throw new Error("目录分页未能继续，请刷新。");
      offset = page.next_offset;
    } while (offset !== null);
    return all;
  }, [workspaceId, projectId, saved]);
  useEffect(() => {
    let live = true;
    const load = async () => {
      const [response, records] = await Promise.all([
        apiClient.GET(`${root}/editing-library`, { params: { path: { workspace_id: workspaceId }, query: { limit: 132 } }, signal: AbortSignal.timeout(12000) }),
        loadNotes(),
      ]);
      const data = unwrapApiResponse(response) as unknown as Catalog;
      if (data.total !== 132 || data.groups.length !== 132 || data.next_offset !== null) throw new Error("原库目录未完整载入，请检查安装状态。");
      if (live) { setCatalog(data); setNotes(records); }
    };
    void load().catch(caught => { if (live) setError(caught instanceof Error ? caught.message : "原库目录暂不可用。"); });
    return () => { live = false; };
  }, [workspaceId, loadNotes]);
  useEffect(() => {
    if (tab !== "resources") return;
    let live = true;
    void apiClient.GET(`${root}/editing-library/resources`, {
      params: { path: { workspace_id: workspaceId }, query: { source, kind: assetKind || undefined, search: resourceSearch, offset: resourceOffset, limit: 100 } }, signal: AbortSignal.timeout(12000),
    }).then(response => {
      const data = unwrapApiResponse(response) as unknown as ResourcePage;
      if (live) { setResourcePage(data); setResourceLoading(false); }
    }).catch(() => { if (live) { setError("资源目录暂不可用，请重试。"); setResourceLoading(false); } });
    return () => { live = false; };
  }, [workspaceId, tab, source, assetKind, resourceSearch, resourceOffset, resourceReload]);
  const filtered = (catalog?.groups || []).filter(g => (!groupKind || g.kind === groupKind) && (!functionFilter || g.primary_function === functionFilter) && `${g.id} ${g.name} ${g.purpose}`.toLowerCase().includes(search.toLowerCase()));
  const functions = [...new Set((catalog?.groups || []).map(g => g.primary_function))];
  const chooseTarget = (item: Target) => {
    const current = noteMap.get(targetKey(item.kind, item.id));
    setTarget(item); setChoice(current?.choice || "consider"); setReason(current?.reason || ""); setHistory(undefined); setMessage("");
  };
  const inspectGroup = async (group: Group) => {
    detailRequest.current = group.id;
    setDetailId(group.id); setDetail(undefined); setError("");
    try {
      const response = await apiClient.GET(`${root}/editing-library/groups/{group_id}`, { params: { path: { workspace_id: workspaceId, group_id: group.id } }, signal: AbortSignal.timeout(12000) });
      const data = unwrapApiResponse(response) as unknown as Detail;
      if (detailRequest.current === group.id) setDetail(data);
    } catch { if (detailRequest.current === group.id) setError("此组详情暂不可用。"); }
  };
  const saveNote = async () => {
    if (!target || !saved || !reason.trim()) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const current = noteMap.get(targetKey(target.kind, target.id));
      const key = JSON.stringify([projectId, target, choice, reason, current?.id]);
      if (!pending.current || pending.current.key !== key) pending.current = { key, id: crypto.randomUUID() };
      const record = unwrapApiResponse(await apiClient.POST(notePath, { params: { path: { workspace_id: workspaceId, project_id: projectId } }, signal: AbortSignal.timeout(12000), body: {
        request_id: pending.current.id, target_kind: target.kind, target_id: target.id, choice, reason, parent_note_id: current?.id,
      } }));
      setNotes(rows => [record, ...rows.filter(r => targetKey(r.target_kind, r.target_id) !== targetKey(record.target_kind, record.target_id))]);
      pending.current = undefined; setMessage("本项目的选组备忘已保存；基础字幕视频不会因此自动改变。"); setHistory(undefined);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "保存暂未确认，请重试。"); try { setNotes(await loadNotes()); } catch { /* Keep the saved request identity when refresh is unavailable. */ } }
    finally { setBusy(false); }
  };
  const showHistory = async () => {
    if (!target) return;
    try {
      const result = unwrapApiResponse(await apiClient.GET(notePath, { params: { path: { workspace_id: workspaceId, project_id: projectId }, query: { latest_only: false, target_kind: target.kind, target_id: target.id, limit: 20 } }, signal: AbortSignal.timeout(12000) }));
      setHistory(result.items);
    } catch { setError("选组历史暂不可用。"); }
  };
  const noteBadge = (kind: TargetKind, id: string) => { const record = noteMap.get(targetKey(kind, id)); return record && record.choice !== "clear" ? <small className={styles.choiceBadge}>{choiceLabel[record.choice]}</small> : null; };
  return <section className={styles.library} aria-label="完整原库目录">
    <header><b>完整原库目录</b><p>所有动效和资源均保留。编码样本只证明对应输入运行过，语义、画面和听感仍需逐片验收。</p></header>
    {catalog && <p className={styles.summary}>
      已登记 {catalog.summary.groups} 组 · {catalog.summary.runtime.sample_rendered || 0} 组有样本 · {catalog.summary.runtime.sample_failed || 0} 组仅有失败记录
      {catalog.summary.runtime.mixed_samples ? ` · ${catalog.summary.runtime.mixed_samples} 组有成功与失败记录` : ""}
      {" · "}{catalog.summary.runtime.unverified || 0} 组待实测<br />
      内置资源 {catalog.summary.bundled_assets} 项 · 外部引用 {catalog.summary.external_references} 项 · 用户画面验收 {catalog.summary.visual_accepted} 组
    </p>}
    <div className={styles.tabs} role="group" aria-label="原库目录分类">{[{ id: "groups" as const, label: "全部动效组" }, { id: "resources" as const, label: "声音与素材" }, { id: "notes" as const, label: "项目选组备忘" }].map(t => <button type="button" key={t.id} aria-pressed={tab === t.id} onClick={() => { setTab(t.id); if (t.id === "resources" && !resourcePage) setResourceLoading(true); }}>{t.label}</button>)}</div>
    {error && <p className={styles.error} role="alert">{error}</p>}
    {!catalog && !error && <p role="status">正在读取全部原库条目…</p>}
    {tab === "groups" && catalog && <>
      <div className={styles.filters}><label>搜索动效<input aria-label="搜索原库动效" value={search} onChange={e => setSearch(e.target.value)} placeholder="组 ID、名称或用途" /></label><label>画面类型<select aria-label="动效画面类型" value={groupKind} onChange={e => setGroupKind(e.target.value)}><option value="">全部</option><option value="visual">画面动效</option><option value="subtitle">字幕动效</option></select></label><label>表达用途<select aria-label="动效表达用途" value={functionFilter} onChange={e => setFunctionFilter(e.target.value)}><option value="">全部用途</option>{functions.map(f => <option key={f} value={f}>{f}</option>)}</select></label></div>
      <p>显示 {filtered.length} / {catalog.total} 组</p>
      <div className={styles.grid} aria-label="原库动效列表">{filtered.map(g => <article key={g.id} data-group-id={g.id}><div><small>{g.id} · {g.kind === "subtitle" ? "字幕" : "画面"}</small><b>{g.name}</b></div><p>{g.purpose}</p><span className={styles.status}>{runtimeLabel[g.runtime_validation] || "待实际验证"}</span>{noteBadge("group", g.id)}<div className={styles.actions}><button type="button" onClick={() => void inspectGroup(g)}>查看详情</button><button type="button" disabled={!saved} onClick={() => chooseTarget({ kind: "group", id: g.id, name: g.name })}>记录选组倾向</button></div></article>)}</div>
      {detailId && <section className={styles.detail} aria-label="动效组详情">
        <b>{detailId} · {catalog.groups.find(g => g.id === detailId)?.name}</b>
        {detail ? <>
          <p>{detail.contract_status === "declared" ? "有原始参数合同" : "保留原始 schema 与入口"}。以下是模板与已核查原入口的外部输入，其他运行依赖仍需按实际分支核对。</p>
          {detail.parameter_contract.classic_authoring_status === "classic_attributes_schema_closed" && <p>经典入口的原 schema 拒绝写入当前文字和时点参数。{detail.parameter_contract.native_profile === "picture-parallel-3" && "原三图变体仅供已配置的内部工作区验证。"}</p>}
          {detail.parameter_contract.website_sidecar_scope === "component_only_until_chart_facts_are_bound" && (
            <p>经典入口已有原生组件样本。组合模板「同期口播与三项占比」使用已校对口播的总数和三个同单位数量。</p>
          )}
          {detail.parameter_contract.website_sidecar_scope === "component_only_pending_original_font_review" && (
            <p>三张原卡已接入实录词点和同期画面。组件编码待原俊雅字体与项目使用授权。</p>
          )}
          {detail.parameter_contract.native_branches?.question && (
            <p>
              {detail.runtime_evidence.some(row => row.native_branch === "question" && row.runtime_validation === "sample_rendered")
                ? "竖排追问已有编码样本。"
                : "竖排追问等待编码样本。"}
              {detail.runtime_evidence.some(row => row.native_branch === "smoke" && row.runtime_validation === "sample_rendered")
                ? "烟雾收尾已有编码样本。"
                : "烟雾收尾需单独核验原透明序列。"}
            </p>
          )}
          {detail.parameter_contract.media_clock_profile?.project_scene_clip_paths && <p>已核对口播取帧规则及 {detail.parameter_contract.media_clock_profile.project_scene_clip_paths.length} 个独立补充素材槽。</p>}
          {!!detail.original_input_variants?.length && <section aria-label="原生输入版本">
            <b>原生输入版本</b>
            <ul>{detail.original_input_variants.map(variant => <li key={variant.id}>
              {variant.id} · {variant.has_encoded_sample ? "有本期编码样本" : "待实际验证"}
              <ul>{variant.dependency_fonts.map(font => <li key={font.id}>{font.display_name} · {localDependencyLabel[font.local_dependency_state]}</li>)}</ul>
            </li>)}</ul>
          </section>}
          {!!detail.original_startup_assets?.length && <section aria-label="原入口启动原件">
            <b>原入口启动原件</b>
            {detail.original_startup_assets.some(input => input.supplement_registry_invalid) && <p>本机补交清单无法核验，请检查版本及格式。</p>}
            <ul>{detail.original_startup_assets.map(input => <li key={input.native_path_pattern}>
              {input.native_path_pattern} · {startupUsageLabel[input.usage]} · 应有 {input.expected_count} 件
              <br />原包内核验 {input.verified_bundled_count}/{input.bundled_count} 件 · 补交核验 {input.verified_supplement_count} 件
              {input.indexed_external_ids.length > 0 && " · 外部原件 " + input.indexed_external_ids.join("、")}
              {input.missing_paths.length > 0 && <details>
                <summary>查看 {input.missing_paths.length} 件未核验原件</summary>
                <ul>{input.missing_paths.map(path => <li key={path}>{path}</li>)}</ul>
              </details>}
            </li>)}</ul>
          </section>}
          {!detail.original_input_variants?.length && (detail.template_dependencies.length ? <ul>{detail.template_dependencies.map(d => <li key={d.id}>
            {kindLabel[d.kind] || d.kind}：{d.display_name} · {dependencyLabel[d.binding_scope] || "需绑定原指定依赖"}{d.local_dependency_state && ` · ${localDependencyLabel[d.local_dependency_state]}`}{d.original_rights === "noncommercial_marked_no_commercial_or_redistribution_claim" && " · 原件标注仅非商用，商用需核对授权"}
          </li>)}</ul> : <p>暂未登记外部输入引用。</p>)}
          <p>已登记 {detail.runtime_evidence.length} 份具体运行记录，画面和听感未验收。</p>
        </> : <p>正在读取本组详情…</p>}
      </section>}
    </>}
    {tab === "resources" && <>
      <div className={styles.filters}><label>资源来源<select aria-label="原库资源来源" value={source} onChange={e => { setSource(e.target.value as typeof source); setAssetKind(""); setResourceOffset(0); setAudioId(""); setResourceLoading(true); }}><option value="bundled">原包内置资源</option><option value="external">原包外部引用</option></select></label><label>资源类型<select aria-label="原库资源类型" value={assetKind} onChange={e => { setAssetKind(e.target.value); setResourceOffset(0); setResourceLoading(true); }}><option value="">全部</option>{(source === "bundled" ? ["font", "sfx", "sfx-processed", "music", "image", "geometry"] : ["font", "model", "media"]).map(k => <option key={k} value={k}>{kindLabel[k]}</option>)}</select></label></div>
      <form className={styles.searchForm} onSubmit={e => { e.preventDefault(); setResourceSearch(resourceDraft); setResourceOffset(0); setResourceLoading(true); setResourceReload(value => value + 1); }}><label>搜索资源<input aria-label="搜索原库资源" value={resourceDraft} onChange={e => setResourceDraft(e.target.value)} maxLength={100} /></label><button type="submit">搜索资源</button></form>
      <p>{source === "external" ? "外部引用记录全部保留；字体、模型和本期素材需明确绑定，历史素材不会自动进入新片。" : "试听使用原包音频。文件名只供检索，播放不会自动标记听感通过。"}</p>
      {resourceLoading && <p role="status">正在读取资源…</p>}
      {resourcePage && <><p>共 {resourcePage.total} 项，当前 {resourcePage.total ? resourceOffset + 1 : 0}–{resourceOffset + resourcePage.resources.length} 项</p><div className={styles.grid} aria-label="原库资源列表">{resourcePage.resources.map(a => <article key={a.id}><div><small>{kindLabel[a.kind] || a.kind}</small><b>{a.display_name}</b></div><small>{a.id}</small><p>{a.availability === "packaged" ? "原包内置" : a.local_dependency_state ? localDependencyLabel[a.local_dependency_state] : "待本任务绑定"}{typeof a.duration_seconds === "number" ? ` · ${a.duration_seconds.toFixed(2)} 秒` : ""}</p>{a.kind === "geometry" && <p>仅几何轮廓，不能充当商品实拍证据。</p>}{a.kind === "image" && <p>原生插画素材，具体语义需按本片核对。</p>}{noteBadge(source === "bundled" ? "bundled_asset" : "external_resource", a.id)}<div className={styles.actions}>{a.audio_preview_supported && <button type="button" disabled={resourceLoading} onClick={() => setAudioId(audioId === a.id ? "" : a.id)}>{audioId === a.id ? "收起试听" : "试听原包音频"}</button>}<button type="button" disabled={!saved || resourceLoading} onClick={() => chooseTarget({ kind: source === "bundled" ? "bundled_asset" : "external_resource", id: a.id, name: a.display_name })}>记录选择倾向</button></div>{audioId === a.id && <audio controls preload="metadata" aria-label={`${a.display_name}试听`} src={`/api/v1/video-studio/workspaces/${encodeURIComponent(workspaceId)}/editing-library/assets/${encodeURIComponent(a.id)}/audio`} onError={() => setError("原包音频暂不可用，请检查资源完整性。")} />}</article>)}</div><div className={styles.actions}><button type="button" disabled={resourceLoading || resourceOffset === 0} onClick={() => { setResourceOffset(Math.max(0, resourceOffset - 100)); setResourceLoading(true); }}>上一页资源</button><button type="button" disabled={resourceLoading || resourcePage.next_offset === null} onClick={() => { if (resourcePage.next_offset !== null) { setResourceOffset(resourcePage.next_offset); setResourceLoading(true); } }}>下一页资源</button></div></>}
    </>}
    {tab === "notes" && <section aria-label="项目选组备忘"><p>记录本项目的选组和资源倾向，不会修改原库或自动改变当前基础字幕视频。</p>{notes.length ? notes.map(n => <article className={styles.memo} key={n.id}><b>{n.target_name} · {n.target_id}</b><p>{choiceLabel[n.choice]} · 第 {n.sequence} 版</p><p>{n.reason}</p><button type="button" onClick={() => chooseTarget({ kind: n.target_kind, id: n.target_id, name: n.target_name })}>修改备忘</button></article>) : <p>暂无选组备忘。可在动效或资源条目中记录。</p>}</section>}
    {!saved && <p>保存当前项目后，可记录独立的项目选组倾向。</p>}
    {target && <section className={styles.noteEditor} aria-label="选组备忘编辑"><b>{target.name} · {target.id}</b><label>本项目选择倾向<select aria-label="本项目选择倾向" value={choice} onChange={e => setChoice(e.target.value as Note["choice"])}>{Object.entries(choiceLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>选择理由<textarea aria-label="选组理由" value={reason} onChange={e => setReason(e.target.value)} rows={3} maxLength={1000} /></label><div className={styles.actions}><button type="button" disabled={busy || !reason.trim() || !saved} onClick={() => void saveNote()}>保存选组备忘</button><button type="button" disabled={!saved} onClick={() => void showHistory()}>查看最近版本</button><button type="button" onClick={() => setTarget(undefined)}>收起备忘</button></div>{history && <ol>{history.map(n => <li key={n.id}>第 {n.sequence} 版 · {choiceLabel[n.choice]}：{n.reason}</li>)}</ol>}</section>}
    {message && <p role="status">{message}</p>}
  </section>;
}
