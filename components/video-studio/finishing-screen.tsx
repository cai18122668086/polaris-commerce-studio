"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Check, ChevronDown, Images, LoaderCircle, RefreshCw, Type } from "lucide-react";
import { ApiError } from "@/lib/api/api-error";
import { mediaUrl } from "@/lib/api/base-url";
import { editingHref, stepHref, worksHref } from "@/features/video-studio/flow-params";
import { BODY_LIMIT, COVER_TEXT_LIMIT, COVER_TEXT_SUGGESTED, TITLE_LIMITS, countChars, defaultCoverText, type Platform } from "@/features/video-studio/works";
import { billableLabel, creditPhrase } from "@/features/video-studio/credit-notes";
import { coverImageUrl, useCoverActions, useCoverCandidates, useFinishingItems, useScriptPlatforms, useWorkVideo, type CoverCandidate, type WorkItem } from "@/features/video-studio/use-finishing";
import { GuidedEmpty } from "./page-hero";
import styles from "./finish-works.module.css";

type Notify = (text: string, tone?: "success" | "error" | "info") => void;
type Draft = { title: string; body: string; coverText: string; highlight: string; coverId: string | null; platform?: Platform };

const PLATFORM_LABEL: Record<Platform, string> = { douyin: "抖音", xiaohongshu: "小红书" };
const uuid = () => crypto.randomUUID();

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError && error.message ? error.message : fallback;
}

/** 最新一轮的两张候选（视频画面 + AI 重绘），再往前是之前的批次与改字版本。 */
function latestRound(covers: CoverCandidate[]): CoverCandidate[] {
  const first = covers.find(cover => !cover.parent_id);
  return first ? covers.filter(cover => cover.request_id === first.request_id).sort((a, b) => a.slot - b.slot) : [];
}

export function FinishingScreen({ workspaceId, batch, item, coverCredits, notify }: {
  workspaceId: string;
  batch: string | null;
  item: string | null;
  coverCredits: number | null;
  notify: Notify;
}) {
  const items = useFinishingItems(workspaceId, { batch, item });
  const actions = useCoverActions(workspaceId);
  const [platform, setPlatform] = useState<Platform>("douyin");
  const [drafts, setDrafts] = useState<Record<string, Partial<Draft>>>({});
  const [bulk, setBulk] = useState(false);
  const list = useMemo(() => (items.data ?? []) as WorkItem[], [items.data]);
  const platforms = useScriptPlatforms(workspaceId, list.map(entry => entry.script_document_id ?? ""));
  // Each work keeps the platform of its script (C1); the page switch is only the default.
  const platformOf = (entry: WorkItem): Platform => drafts[entry.id]?.platform ?? platforms.data?.[entry.script_document_id ?? ""] ?? platform;
  const ready = list.filter(entry => entry.stage === "finishing" || entry.stage === "done");
  const saved = list.filter(entry => entry.stage === "done").length;
  // B4：还没剪完的不进成片行（不能生成封面），剪完后 15 秒内自动出现；没剪成的单独列出、回剪辑页处理。
  const unfinished = list.filter(entry => entry.stage === "talking" || entry.stage === "editing");
  const cutting = unfinished.filter(entry => entry.status !== "failed");

  // Edits only; untouched fields fall back to what the work item already has.
  const draftOf = (entry: WorkItem): Draft => ({
    title: entry.publish_title ?? "", body: entry.publish_body ?? "",
    coverText: defaultCoverText(entry.publish_title), highlight: "", coverId: entry.cover_asset_id ?? null,
    ...drafts[entry.id],
  });
  const update = (id: string, patch: Partial<Draft>) => setDrafts(previous => ({ ...previous, [id]: { ...previous[id], ...patch } }));

  const generateFor = async (entry: WorkItem, round: number) => {
    const draft = draftOf(entry);
    const text = draft.coverText.trim();
    if (!text) { notify("先填写封面大字", "error"); return false; }
    try {
      await actions.generate.mutateAsync({ request_id: uuid(), work_item_id: entry.id, cover_text: text, highlight: draft.highlight || null, platform: platformOf(entry), round });
      return true;
    } catch (error) {
      notify(errorText(error, "封面没有生成成功，请稍后再试。"), "error");
      return false;
    }
  };

  const generateAll = async () => {
    setBulk(true);
    const targets = ready.filter(entry => entry.stage !== "done");
    const results = await Promise.all(targets.map(entry => generateFor(entry, 0)));
    setBulk(false);
    const ok = results.filter(Boolean).length;
    if (ok) notify(`已开始为 ${ok} 条视频生成封面，每条 2 张候选`, "success");
  };

  if (items.isPending) return <p className={styles.loading} role="status"><LoaderCircle className={styles.spin} size={16} />正在读取要成片的视频…</p>;
  if (items.isError) return <p role="alert" className={styles.alert}>暂时读不到这批视频。<button type="button" className={styles.linkButton} onClick={() => void items.refetch()}>重试</button></p>;
  const waitingNote = unfinished.length > 0 && <div className={styles.waiting} role="status" aria-label="还没剪完的视频">
    {cutting.length > 0 && <p><LoaderCircle className={styles.spin} size={15} /><span>还有 {cutting.length} 条剪辑中，完成后自动出现在这里，不用刷新。</span></p>}
    <ul>{unfinished.map(entry => <li key={entry.id}>
      <span className={styles.waitingIndex}>{String(list.indexOf(entry) + 1).padStart(2, "0")}</span>
      <span className={styles.waitingTitle}>{entry.publish_title || "未命名视频"}</span>
      {entry.status === "failed"
        ? <span className={styles.waitingState}>{entry.stage === "talking" ? "口播没有生成成功" : "剪辑没有成功"} · <Link href={entry.stage === "talking" ? stepHref("voice", { batch: entry.batch_id }) : editingHref(entry.batch_id)} className={styles.linkButton}>回到这一步</Link></span>
        : <span className={styles.waitingState}>{entry.stage === "talking" ? "口播生成中" : "剪辑中"}，完成后自动出现</span>}
    </li>)}</ul>
  </div>;

  if (list.length && !ready.length) return <section className={styles.finish} aria-label="成片">
    <header className={styles.finishHead}><div><h1>成片</h1><p>这一批还没有剪完的视频。第一条剪完就会出现在这里，可以先去忙别的。</p></div></header>
    {waitingNote}
  </section>;
  if (!list.length) return <GuidedEmpty title="还没有待成片的视频" description="剪辑完成的视频会来到这里：配封面、定标题和正文，保存后出现在「我的作品」。" steps={["在「智能剪辑」剪好一批视频", "回到这里一键生成封面", "挑封面、改标题，保存到我的作品"]} action={<Link className={styles.primary} href={editingHref(batch)}>去智能剪辑</Link>} motif="works" />;

  const pending = ready.filter(entry => entry.stage !== "done").length;
  const bulkCost = coverCredits != null ? pending * coverCredits : null;

  return <section className={styles.finish} aria-label="成片">
    <header className={styles.finishHead}>
      <div>
        <h1>成片</h1>
        <p>给每条视频配上封面、标题和正文。封面上的字和你填的一字不差，不会压到人脸。</p>
      </div>
      <dl className={styles.facts}>
        <div><dt>本批</dt><dd>{list.length} 条</dd></div>
        {unfinished.length > 0 && <div><dt>可成片</dt><dd>{ready.length} 条</dd></div>}
        <div><dt>已保存</dt><dd>{saved} 条</dd></div>
      </dl>
    </header>
    <div className={styles.toolbar}>
      <span className={styles.toolbarLabel}>默认平台</span>
      <div className={styles.segment} role="radiogroup" aria-label="默认发布平台">
        {(Object.keys(PLATFORM_LABEL) as Platform[]).map(key => <button key={key} type="button" role="radio" aria-checked={platform === key} onClick={() => setPlatform(key)}>{PLATFORM_LABEL[key]}</button>)}
      </div>
      <span className={styles.toolbarNote}>每条出 2 张：1 张用视频画面（免费），1 张 AI 重绘（{creditPhrase(coverCredits, { per: "张", failureFree: true })}）</span>
      <button type="button" className={styles.primary} disabled={!pending || bulk || actions.generate.isPending} onClick={() => void generateAll()}>
        {bulk ? <LoaderCircle className={styles.spin} size={16} /> : <Images size={16} />}{pending ? billableLabel("一键给全部生成封面", bulkCost) : "一键给全部生成封面"}
      </button>
    </div>
    <ol className={styles.rows}>
      {ready.map(entry => <FinishRow key={entry.id} index={list.indexOf(entry)} workspaceId={workspaceId} entry={entry} draft={draftOf(entry)} platform={platformOf(entry)}
        onChange={patch => update(entry.id, patch)} onGenerate={round => void generateFor(entry, round)} generating={actions.generate.isPending && actions.generate.variables?.work_item_id === entry.id}
        actions={actions} notify={notify} />)}
    </ol>
    {waitingNote}
    {saved === list.length && <div className={styles.allDone}><Check size={16} />这一批都已保存。<Link href={worksHref(batch)} className={styles.linkButton}>去我的作品看看</Link></div>}
  </section>;
}

function FinishRow({ index, workspaceId, entry, draft, platform, onChange, onGenerate, generating, actions, notify }: {
  index: number;
  workspaceId: string;
  entry: WorkItem;
  draft: Draft;
  platform: Platform;
  onChange: (patch: Partial<Draft>) => void;
  onGenerate: (round: number) => void;
  generating: boolean;
  actions: ReturnType<typeof useCoverActions>;
  notify: Notify;
}) {
  const covers = useCoverCandidates(workspaceId, entry.id);
  const video = useWorkVideo(workspaceId, entry);
  const [showScript, setShowScript] = useState(false);
  const all = covers.data ?? [];
  const round = latestRound(all);
  const rounds = new Set(all.filter(cover => !cover.parent_id).map(cover => cover.request_id)).size;
  const retexts = all.filter(cover => cover.parent_id && cover.status === "ready").slice(0, 2);
  // The saved (or picked) cover stays in view while a new round is generating.
  const kept = all.find(cover => cover.id === (draft.coverId ?? entry.cover_asset_id) && cover.status === "ready");
  const shown = [...(kept && !retexts.includes(kept) && !round.includes(kept) ? [kept] : []), ...retexts, ...round];
  // Until the user picks one, the first ready cover of the newest round is chosen.
  const chosenId = draft.coverId ?? round.find(cover => cover.status === "ready")?.id ?? null;
  const selected = all.find(cover => cover.id === chosenId && cover.status === "ready") ?? null;
  const busy = round.some(cover => cover.status === "queued" || cover.status === "running");
  // B5（L3 重剪）：条目的视频比最新一轮封面新，提示可以重新生成封面。
  const videoUpdatedAt = (entry as { video_updated_at?: string | null }).video_updated_at ?? null;
  const videoChanged = Boolean(videoUpdatedAt && round.length && round.every(cover => Date.parse(cover.created_at) < Date.parse(videoUpdatedAt)));
  const notReady = entry.stage === "talking" || entry.stage === "editing";
  const limit = TITLE_LIMITS[platform];
  const titleCount = countChars(draft.title);
  const coverCount = countChars(draft.coverText);
  const done = entry.stage === "done" && entry.cover_asset_id === chosenId && entry.publish_title === draft.title.trim() && (entry.publish_body ?? "") === draft.body;

  const retext = async () => {
    const base = selected ?? round.find(cover => cover.status === "ready");
    if (!base) return;
    try {
      const made = await actions.retext.mutateAsync({ candidateId: base.id, itemId: entry.id, cover_text: draft.coverText.trim(), highlight: draft.highlight || null, request_id: uuid() });
      onChange({ coverId: made.id });
      notify("封面大字已更新（免费）", "success");
    } catch (error) { notify(errorText(error, "改字没有成功。"), "error"); }
  };

  const save = async () => {
    if (!selected) { notify("先选一张封面", "error"); return; }
    if (!draft.title.trim()) { notify("请填写发布标题", "error"); return; }
    try {
      await actions.finish.mutateAsync({ itemId: entry.id, expected_version: entry.version, cover_candidate_id: selected.id, publish_title: draft.title.trim(), publish_body: draft.body });
      notify("已保存到我的作品", "success");
    } catch (error) { notify(errorText(error, "保存没有成功，请刷新后再试。"), "error"); }
  };

  return <li className={styles.row} aria-label={`第 ${index + 1} 条`}>
    <div className={styles.rowVideo}>
      <span className={styles.rowIndex}>{String(index + 1).padStart(2, "0")}</span>
      {video.data ? <video controls playsInline preload="metadata" src={mediaUrl(video.data)} aria-label="视频预览" /> : <div className={styles.videoPlaceholder}>{notReady ? "剪辑完成后可成片" : video.isPending && video.fetchStatus !== "idle" ? "视频读取中" : "暂时没有可播放的成片"}</div>}
    </div>
    <div className={styles.rowCovers}>
      <div className={styles.rowLabel}><b>封面</b>{shown.length > 0 && <span>点选一张</span>}</div>
      {shown.length ? <div className={styles.coverStrip} role="radiogroup" aria-label="封面候选">
        {shown.map(cover => <CoverChoice key={cover.id} workspaceId={workspaceId} cover={cover} selected={cover.id === chosenId} onSelect={() => onChange({ coverId: cover.id })} />)}
      </div> : <div className={styles.coverEmpty}>{busy || generating ? <><LoaderCircle className={styles.spin} size={16} />正在生成…</> : "还没有封面"}</div>}
      <label className={styles.field}>
        <span>封面大字 <small className={coverCount > COVER_TEXT_SUGGESTED ? styles.warn : ""}>{coverCount}/{COVER_TEXT_LIMIT}{coverCount > COVER_TEXT_SUGGESTED ? " · 建议 14 字以内，字会更大" : ""}</small></span>
        <input value={draft.coverText} maxLength={COVER_TEXT_LIMIT} onChange={event => onChange({ coverText: event.target.value })} placeholder="默认用发布标题，可以单独改" />
      </label>
      <label className={styles.field}>
        <span>加强的词 <small>可空，必须是封面大字里连续的一段</small></span>
        <input value={draft.highlight} maxLength={COVER_TEXT_LIMIT} onChange={event => onChange({ highlight: event.target.value })} placeholder="例如：冰丝" />
      </label>
      <div className={styles.coverActions}>
        {!round.length
          ? <button type="button" className={styles.secondary} disabled={notReady || generating} onClick={() => onGenerate(0)}><Images size={15} />生成封面</button>
          : <button type="button" className={styles.secondary} disabled={notReady || busy || generating} onClick={() => onGenerate(rounds)}><RefreshCw size={15} />换一批</button>}
        <button type="button" className={styles.ghost} disabled={!round.some(cover => cover.status === "ready") || !draft.coverText.trim() || actions.retext.isPending} onClick={() => void retext()}><Type size={15} />只改封面上的字（免费）</button>
      </div>
      {videoChanged && <p className={styles.note} role="status">视频已更新，可以点「换一批」重新生成封面。</p>}
      {round.map(cover => cover.message && <p key={cover.id} className={styles.note}>{cover.message}</p>)}
    </div>
    <div className={styles.rowText}>
      <div className={styles.rowPlatform} role="radiogroup" aria-label="这条的发布平台">
        <span>发布到</span>
        {(Object.keys(PLATFORM_LABEL) as Platform[]).map(key => <button key={key} type="button" role="radio" aria-checked={platform === key} onClick={() => onChange({ platform: key })}>{PLATFORM_LABEL[key]}</button>)}
      </div>
      <label className={styles.field}>
        <span>发布标题 <small className={titleCount > limit ? styles.over : ""}>{titleCount}/{limit}</small></span>
        <input value={draft.title} maxLength={60} onChange={event => onChange({ title: event.target.value })} />
      </label>
      {titleCount > limit && <p className={styles.over}>超过{PLATFORM_LABEL[platform]}标题上限，发布时会被截断。</p>}
      <label className={styles.field}>
        <span>发布正文 <small>{countChars(draft.body)}/{BODY_LIMIT}</small></span>
        <textarea rows={5} value={draft.body} maxLength={2000} onChange={event => onChange({ body: event.target.value })} placeholder="正文和话题标签，可直接复制去发布" />
      </label>
      {entry.script_text && <div className={styles.script}>
        <button type="button" aria-expanded={showScript} onClick={() => setShowScript(value => !value)}>口播稿<ChevronDown size={14} className={showScript ? styles.flip : ""} /></button>
        {showScript && <p>{entry.script_text}</p>}
      </div>}
      <div className={styles.saveLine}>
        {done ? <span className={styles.saved}><Check size={15} />已保存到我的作品</span> : <span className={styles.muted}>{selected ? `已选：${selected.background_label}封面` : "未选封面"}</span>}
        <button type="button" className={styles.primary} disabled={notReady || !selected || actions.finish.isPending || done} onClick={() => void save()}>保存到我的作品</button>
      </div>
    </div>
  </li>;
}

function CoverChoice({ workspaceId, cover, selected, onSelect }: { workspaceId: string; cover: CoverCandidate; selected: boolean; onSelect: () => void }) {
  if (cover.status !== "ready") {
    return <div className={styles.coverPending} aria-busy={cover.status !== "failed"}>
      {cover.status === "failed" ? <span>{cover.message ?? "没有生成成功，未扣积分"}</span> : <><LoaderCircle className={styles.spin} size={16} /><span>{cover.background === "ai" ? "AI 重绘中" : "排版中"}</span></>}
    </div>;
  }
  return <button type="button" role="radio" aria-checked={selected} className={`${styles.coverChoice} ${selected ? styles.coverSelected : ""}`} onClick={onSelect} title={cover.cover_text}>
    <span className={styles.coverImage}>
      <img src={mediaUrl(coverImageUrl(workspaceId, cover.id, "thumb"))} alt={`封面：${cover.cover_text}`} loading="lazy" />
      {selected && <span className={styles.coverCheck} aria-hidden="true"><Check size={13} strokeWidth={2.6} /></span>}
    </span>
    <span className={styles.coverTag}>{cover.parent_id ? "改字版" : cover.background_label}{cover.checks?.picture_cool_hint ? " · 画面偏冷" : ""}</span>
  </button>;
}
