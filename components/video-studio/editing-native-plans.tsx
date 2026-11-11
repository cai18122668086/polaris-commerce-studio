"use client";

import { useEffect, useRef, useState } from "react";
import { minDistinctMotionGroups, repeatedEffectsForReduction } from "@/features/video-studio/editing-density";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import { EditingImageEdits } from "./editing-image-edits";
import styles from "./editing-workspace.module.css";

type Plan = components["schemas"]["EditingNativePlanResponse"];
type NativeEdits = components["schemas"]["NativeRenderEdits"];
type Highlight = components["schemas"]["NativeHighlightEdit"];
type HighlightTarget = components["schemas"]["EditingHighlightTarget"];
type ImageEdit = components["schemas"]["NativeImageEdit"];
type EffectEdit = components["schemas"]["NativeEffectEdit"];
type EffectTarget = components["schemas"]["EditingEffectTarget"];
type MusicOptions = components["schemas"]["EditingMusicOptions"];
type Controls = { music: "keep" | "lower" | "off"; musicTrackId: string; segments: string[]; highlights: Highlight[]; images: ImageEdit[]; effects: EffectEdit[] };
export type EditingRevisionSelection = {
  planId: string;
  taskId: string;
  kind: "preview" | "layout_failure";
  preview?: components["schemas"]["EditingPreviewBase"] | null;
  edits?: NativeEdits | null;
  layoutFindings?: components["schemas"]["EditingLayoutFinding"][] | null;
};
const defaultControls: Controls = { music: "keep", musicTrackId: "", segments: [], highlights: [], images: [], effects: [] };
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;

export function EditingNativePlans({ workspaceId, projectId, onCreated, plansVersion, revisionSelection, onClearRevisionSelection }: {
  workspaceId: string; projectId: string; onCreated: () => Promise<void>; plansVersion: number;
  revisionSelection?: EditingRevisionSelection; onClearRevisionSelection: () => void;
}) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const revealedRevision = useRef("");
  useEffect(() => {
    if (!revisionSelection) { revealedRevision.current = ""; return; }
    const key = `${revisionSelection.planId}:${revisionSelection.taskId}`;
    const target = document.getElementById(`editing-native-plan-${revisionSelection.planId}`);
    if (target && revealedRevision.current !== key) {
      revealedRevision.current = key;
      target.scrollIntoView({ block: "start" });
    }
  }, [plans, revisionSelection]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [controls, setControls] = useState<Record<string, Controls>>({});
  const [highlightTargets, setHighlightTargets] = useState<Record<string, HighlightTarget[]>>({});
  const [loadingHighlights, setLoadingHighlights] = useState<string[]>([]);
  const [effectTargets, setEffectTargets] = useState<Record<string, EffectTarget[]>>({});
  const [loadingEffects, setLoadingEffects] = useState<string[]>([]);
  const [musicOptions, setMusicOptions] = useState<Record<string, MusicOptions | null>>({});
  const [loadingMusic, setLoadingMusic] = useState<string[]>([]);
  const intent = useRef<{ key: string; id: string } | undefined>(undefined);
  const live = useRef(true);
  const selectedPlan = revisionSelection?.planId;
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController();
    void apiClient.GET(`${root}/projects/{project_id}/editing-native-plans`, {
      params: { path: { workspace_id: workspaceId, project_id: projectId }, query: { include_plan_id: selectedPlan } },
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]),
    }).then(result => { if (!controller.signal.aborted) { setPlans(unwrapApiResponse(result)); setLoaded(true); setError(""); } })
      .catch(() => { if (!controller.signal.aborted) setError("暂时无法读取动效编排，请重试。"); });
    return () => controller.abort();
  }, [workspaceId, projectId, reload, plansVersion, selectedPlan]);
  const loadHighlights = async (plan: Plan) => {
    if (!plan.highlight_edit_available || highlightTargets[plan.id] || loadingHighlights.includes(plan.id)) return;
    setLoadingHighlights(previous => [...previous, plan.id]);
    try {
      const targets = unwrapApiResponse(await apiClient.GET(`${root}/projects/{project_id}/editing-native-plans/{plan_id}/highlight-options`, {
        params: { path: { workspace_id: workspaceId, project_id: projectId, plan_id: plan.id } },
        signal: AbortSignal.timeout(12000),
      }));
      if (live.current) setHighlightTargets(previous => ({ ...previous, [plan.id]: targets }));
    } catch (caught) {
      if (live.current) setError(caught instanceof Error ? caught.message : "暂时无法读取本段的实录短语。");
    } finally {
      if (live.current) setLoadingHighlights(previous => previous.filter(id => id !== plan.id));
    }
  };
  const loadEffects = async (plan: Plan) => {
    if (effectTargets[plan.id] || loadingEffects.includes(plan.id)) return;
    setLoadingEffects(previous => [...previous, plan.id]);
    try {
      const targets = unwrapApiResponse(await apiClient.GET(`${root}/projects/{project_id}/editing-native-plans/{plan_id}/effect-options`, {
        params: { path: { workspace_id: workspaceId, project_id: projectId, plan_id: plan.id } },
        signal: AbortSignal.timeout(12000),
      }));
      if (live.current) setEffectTargets(previous => ({ ...previous, [plan.id]: targets }));
    } catch (caught) {
      if (live.current) setError(caught instanceof Error ? caught.message : "暂时无法读取本段可替换的原生动效。");
    } finally {
      if (live.current) setLoadingEffects(previous => previous.filter(id => id !== plan.id));
    }
  };
  const loadMusic = async (plan: Plan) => {
    if (plan.id in musicOptions || loadingMusic.includes(plan.id)) return;
    setLoadingMusic(previous => [...previous, plan.id]);
    try {
      const options = unwrapApiResponse(await apiClient.GET(`${root}/projects/{project_id}/editing-native-plans/{plan_id}/music-options`, {
        params: { path: { workspace_id: workspaceId, project_id: projectId, plan_id: plan.id } },
        signal: AbortSignal.timeout(12000),
      }));
      if (live.current) setMusicOptions(previous => ({ ...previous, [plan.id]: options }));
    } catch (caught) {
      if (live.current) setError(caught instanceof Error ? caught.message : "暂时无法读取可替换的原库背景音乐。");
    } finally {
      if (live.current) setLoadingMusic(previous => previous.filter(id => id !== plan.id));
    }
  };
  const render = async (plan: Plan, selected: Controls, earlier?: EditingRevisionSelection) => {
    setBusy(plan.id); setError("");
    try {
      const segments = selected.segments.slice().sort();
      const music = selected.music === "keep" ? null : selected.music;
      const musicTrackId = music !== "off" && selected.musicTrackId;
      const bySlot = (a: Highlight | ImageEdit, b: Highlight | ImageEdit) =>
        a.beat_id.localeCompare(b.beat_id) || a.path.localeCompare(b.path);
      const highlights = selected.highlights.slice().sort(bySlot);
      const images = selected.images.slice().sort(bySlot);
      const effects = selected.effects.slice().sort((a, b) => a.beat_id.localeCompare(b.beat_id));
      const edits: NativeEdits | undefined = music || musicTrackId || segments.length || highlights.length || images.length || effects.length
        ? {
          music, source_only_beat_ids: segments,
          ...(musicTrackId ? { music_track_id: musicTrackId } : {}),
          ...(highlights.length ? { highlight_edits: highlights } : {}),
          ...(images.length ? { image_edits: images } : {}),
          ...(effects.length ? { effect_edits: effects } : {}),
        }
        : undefined;
      const key = JSON.stringify([plan.id, edits, earlier?.preview]);
      if (intent.current?.key !== key) intent.current = { key, id: crypto.randomUUID() };
      const created = unwrapApiResponse(await apiClient.POST(`${root}/editing-tasks`, {
        params: { path: { workspace_id: workspaceId } }, signal: AbortSignal.timeout(12000),
        body: { request_id: intent.current.id, source_id: plan.source_id, options: {
          mode: "native_plan", native_plan_id: plan.id, language: "zh",
          source_subtitles: plan.source_subtitles, caption_font_id: "font-d1961be1161ea1be",
          native_edits: edits, delivery: "preview_first", preview_base: earlier?.preview ?? undefined,
        } },
      }));
      intent.current = undefined;
      if (live.current) { await onCreated(); requestAnimationFrame(() => document.getElementById(`editing-task-${created.id}`)?.scrollIntoView({ block: "start" })); }
    } catch (caught) { if (live.current) setError(caught instanceof Error ? caught.message : "出片请求暂未确认，再次点击会查询同一请求。"); }
    finally { if (live.current) setBusy(""); }
  };
  return <section id="editing-native-plans" aria-label="动效编排候选">
    <b>已有动效编排候选</b>
    <p className={styles.note}>每份候选绑定原片、逐词转录和选组版本。先看代理预览，再确认并下载对应的高清文件。</p>
    {!loaded && !error && <p role="status">正在读取本版编排…</p>}
    {loaded && plans.length === 0 && !error && <p>当前项目还没有保存的编排。</p>}
    {plans.filter((plan, index) => revisionSelection ? plan.id === revisionSelection.planId : showHistory || index < 4).map(plan => {
      const earlier = revisionSelection?.planId === plan.id ? revisionSelection : undefined;
      const key = earlier ? `${plan.id}/${earlier.taskId}` : plan.id;
      const failedBeats = new Set(earlier?.layoutFindings?.map(finding => finding.beat_id));
      const initial = earlier?.edits ? {
        music: earlier.edits.music ?? "keep",
        musicTrackId: earlier.edits.music_track_id ?? "",
        segments: earlier.edits.source_only_beat_ids ?? [],
        highlights: earlier.edits.highlight_edits ?? [],
        images: earlier.edits.image_edits ?? [],
        effects: earlier.edits.effect_edits ?? [],
      } satisfies Controls : defaultControls;
      const selected = controls[key] || initial;
      const change = (update: Partial<Controls>) => setControls(current => ({
        ...current, [key]: { ...(current[key] || initial), ...update },
      }));
      const editable = plan.beats.filter(beat => beat.source_only_available);
      const replacements = new Map(selected.effects.map(edit => [edit.beat_id, edit.group_id]));
      const activeEffects = plan.beats.filter(beat => beat.group_id !== "Z-M00" && !selected.segments.includes(beat.id))
        .map(beat => ({ ...beat, group_id: replacements.get(beat.id) ?? beat.group_id }));
      const activeGroups = new Set(activeEffects.map(beat => beat.group_id));
      const missingDependencies = activeEffects.some(beat =>
        beat.dependency_blocker && !replacements.has(beat.id),
      );
      const repeated = repeatedEffectsForReduction(activeEffects, new Set([
        ...selected.highlights.map(edit => edit.beat_id), ...selected.images.map(edit => edit.beat_id), ...replacements.keys(),
      ]));
      const available = plan.render_available && plan.continuous_preview_available;
      const trackOptions = musicOptions[plan.id];
      const audition = selected.musicTrackId
        ? trackOptions?.choices.find(track => track.asset_id === selected.musicTrackId)
        : trackOptions?.original;
      return <article key={plan.id} id={`editing-native-plan-${plan.id}`}>
      <b>{plan.audience_question}</b>
      {earlier && <p className={styles.note}>
        {earlier.kind === "layout_failure" ? "调整排版未通过的版本" : "继续调整预览"} <a href={`#editing-task-${earlier.taskId}`}>{earlier.taskId.slice(0, 8)}</a>
        {" "}<button type="button" disabled={!!busy} onClick={onClearRevisionSelection}>退出本次调整</button>
      </p>}
      {plan.overlay_template && <p className={styles.note}>组合模板 · {plan.overlay_template.name}</p>}
      <p>{plan.origin === "operator_candidate" ? "人工工程候选 · 未经人工验收" : "腾力模型候选 · 待核对"}</p>
      <details><summary>编排与原生诊断详情</summary><ul>{plan.beats.map(beat => <li key={beat.id}>
        {beat.group_id} · {beat.text}<br />{beat.reason}
        {beat.question_gloss && <p className={styles.note}>问号英文释义 · {beat.question_gloss} · 待核对</p>}
        {beat.dependency_blocker && !selected.segments.includes(beat.id) && !replacements.has(beat.id) &&
          <p className={styles.error}>{beat.dependency_blocker}</p>}
      </li>)}</ul>
      {(plan.warnings.length > 0 || plan.missing_materials.length > 0) && <p>{[...plan.warnings, ...plan.missing_materials].join("；")}</p>}
      </details>
      {available && (plan.music_edit_available || editable.length > 0 || plan.highlight_edit_available || plan.image_edit_available) && <details key={key} open={earlier ? true : undefined}>
        <summary>调整本次出片</summary>
        <p className={styles.note}>调整随这次出片保存。勾选保留原景的段落仍显示主字幕，该段动效和绑定音效会关闭。</p>
        {repeated.length > 0 && <button type="button" disabled={!!busy}
          onClick={() => change({ segments: [...selected.segments, ...repeated] })}>精简 {repeated.length} 段重复动效</button>}
        {repeated.length > 0 && <p className={styles.note}>预选部分重复入场为原景，保留每种动效的首次出现和已手动调整的段落。提交前可逐段取消勾选。</p>}
        {plan.music_edit_available && <label>本次背景音乐
          <select value={selected.music} disabled={!!busy} onChange={event => change({
            music: event.target.value as Controls["music"],
            ...(event.target.value === "off" ? { musicTrackId: "" } : {}),
          })}>
            <option value="keep">沿用编排</option><option value="lower">降低 6 dB</option><option value="off">关闭背景音乐</option>
          </select>
        </label>}
        {plan.music_edit_available && selected.music !== "off" && <details onToggle={event => {
          if (event.currentTarget.open) void loadMusic(plan);
        }}>
          <summary>试听和更换背景音乐</summary>
          {loadingMusic.includes(plan.id) && <p role="status">正在核对原库曲目…</p>}
          {trackOptions === null && <p>此编排的背景音乐需要沿用原有分轨。</p>}
          {trackOptions && <>
            <label>原库背景音乐
              <select value={selected.musicTrackId} disabled={!!busy} onChange={event => change({ musicTrackId: event.target.value })}>
                <option value="">沿用 {trackOptions.original.name}</option>
                {selected.musicTrackId && !audition && <option value={selected.musicTrackId}>此前曲目当前不可用</option>}
                {trackOptions.choices.map(track => <option key={track.asset_id} value={track.asset_id}>{track.name} · {Math.round(track.duration_seconds)} 秒</option>)}
              </select>
            </label>
            {audition && <audio key={audition.asset_id} controls preload="none" aria-label={`${audition.name}试听`}
              src={`/api/v1/video-studio/workspaces/${encodeURIComponent(workspaceId)}/editing-library/assets/${encodeURIComponent(audition.asset_id)}/audio`} />}
            <p className={styles.note}>更换后从新曲目的开头播放，沿用原编排的音乐入点、出点和淡入淡出。</p>
          </>}
        </details>}
        {editable.map(beat => <label key={beat.id}>
          <input type="checkbox" disabled={!!busy} checked={selected.segments.includes(beat.id)} onChange={event => change({
            segments: event.target.checked ? [...selected.segments, beat.id] : selected.segments.filter(id => id !== beat.id),
            highlights: event.target.checked ? selected.highlights.filter(edit => edit.beat_id !== beat.id) : selected.highlights,
            images: event.target.checked ? selected.images.filter(edit => edit.beat_id !== beat.id) : selected.images,
            effects: event.target.checked ? selected.effects.filter(edit => edit.beat_id !== beat.id) : selected.effects,
          })} />
          保留原景 · {beat.text}{failedBeats.has(beat.id) && " · 排版待调整"}
        </label>)}
        {plan.overlay_template && <details open={earlier?.kind === "layout_failure" ? true : undefined} onToggle={event => {
          if (event.currentTarget.open) void loadEffects(plan);
        }}>
          <summary>单段更换动效</summary>
          <p className={styles.note}>沿用这一段的实录词点，选择同模板内匹配的原生文字动效。生成时会检查实际画面排版。</p>
          {loadingEffects.includes(plan.id) && <p role="status">正在核对本段可选动效…</p>}
          {effectTargets[plan.id]?.length === 0 && <p>本候选暂无满足同一段词点和字数的替换动效。</p>}
          {effectTargets[plan.id]?.map(target => {
            const beat = plan.beats.find(item => item.id === target.beat_id);
            if (!beat) return null;
            return <label key={beat.id}>{beat.text}{failedBeats.has(beat.id) && " · 排版待调整"}
              <select aria-label={`更换动效 · ${beat.text}`} disabled={!!busy || selected.segments.includes(beat.id)}
                value={replacements.get(beat.id) ?? ""} onChange={event => {
                  const next = selected.effects.filter(edit => edit.beat_id !== beat.id);
                  if (event.target.value) next.push({ beat_id: beat.id, group_id: event.target.value });
                  change({ effects: next });
                }}>
                <option value="">沿用 {beat.group_id}</option>
                {target.choices.map(choice => <option key={choice.group_id} value={choice.group_id}>{choice.group_id} · {choice.name}</option>)}
              </select>
            </label>;
          })}
        </details>}
        {plan.highlight_edit_available && <details onToggle={event => {
          if (event.currentTarget.open) void loadHighlights(plan);
        }}>
          <summary>改动效强调词</summary>
          <p className={styles.note}>从这一段的实录短语中选择，动效会在新短语的词点入场。保存随本次预览生效。</p>
          {loadingHighlights.includes(plan.id) && <p role="status">正在读取实录短语…</p>}
          {highlightTargets[plan.id]?.length === 0 && <p>本候选暂时没有符合原动效字数和时长的替代短语。</p>}
          {highlightTargets[plan.id]?.map(target => {
            const belongs = (edit: Highlight) => edit.beat_id === target.beat_id && edit.path === target.path;
            const active = selected.highlights.find(belongs);
            const chosen = target.options.findIndex(option => option.first_token_id === active?.first_token_id && option.last_token_id === active.last_token_id);
            return <label key={target.beat_id + target.path}>{target.label} · {target.current_text}
              <select aria-label={target.label + " · " + target.current_text}
                disabled={!!busy || selected.segments.includes(target.beat_id)} value={chosen < 0 ? "" : String(chosen)}
                onChange={event => {
                  const option = event.target.value === "" ? undefined : target.options[Number(event.target.value)];
                  const next = selected.highlights.filter(edit => !belongs(edit));
                  if (option) next.push({
                    beat_id: target.beat_id, path: target.path,
                    first_token_id: option.first_token_id, last_token_id: option.last_token_id,
                  });
                  change({ highlights: next });
                }}>
                <option value="">沿用「{target.current_text}」</option>
                {target.options.map((option, index) => <option key={option.first_token_id + option.last_token_id} value={index}>{option.text}</option>)}
              </select>
            </label>;
          })}
        </details>}
        {plan.image_edit_available && <EditingImageEdits workspaceId={workspaceId} projectId={projectId} planId={plan.id}
          selected={selected.images} sourceOnly={selected.segments} disabled={!!busy} onChange={images => change({ images })} />}
      </details>}
      {available ? <>
        <p className={styles.note}>本次计划使用 {activeGroups.size} 种动效，共出现 {activeEffects.length} 次。{activeGroups.size < minDistinctMotionGroups && "请保留至少五种不同动效。"}</p>
        {missingDependencies && <p className={styles.note}>请补齐标出的原库依赖，或在「调整本次出片」中调整对应段落。</p>}
        <button type="button" onClick={() => void render(plan, selected, earlier)} disabled={!!busy || missingDependencies || activeGroups.size < minDistinctMotionGroups}>{busy === plan.id ? "正在提交…" : earlier ? "生成新版代理预览" : "生成代理预览"}</button>
      </> : <p className={styles.note}>{plan.render_available
        ? "历史验证候选 · 待适配连续人物底片与组合动效"
        : "该编排当前不可出片。"}</p>}
    </article>})}
    {!revisionSelection && plans.length > 4 && <button type="button" onClick={() => setShowHistory(value => !value)}>{showHistory ? "收起历史编排" : "查看其他历史编排"}</button>}
    {error && <p role="alert" className={styles.error}>{error} <button type="button" onClick={() => setReload(n => n + 1)}>重新读取编排</button></p>}
  </section>;
}
