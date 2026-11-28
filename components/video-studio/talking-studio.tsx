"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, AudioLines, BookOpenText, Check, CopyCheck, Download, FileText, Flame, Pause, Play, Plus, RotateCcw, Search, Trash2, Upload, UsersRound, X } from "lucide-react";
import type { useVideoLibrary, VideoAvatar, VideoVoice } from "@/features/video-studio/library";
import type { useVoiceClones } from "@/features/video-studio/voice-clones";
import { usePersonas, type VideoPersona } from "@/features/video-studio/personas";
import { AvatarCreateDrawer } from "./avatar-create-drawer";
import { PersonaCreateDrawer } from "./persona-create-drawer";
import { VoiceCloneDrawer } from "./voice-clone-drawer";
import { generationProgress } from "@/features/video-studio/generation-progress";
import { scriptStats } from "@/features/video-studio/script-library-format";
import { editingHref, parseFlowParams, voiceHref } from "@/features/video-studio/flow-params";
import { creditPhrase, FREE_TRIAL_SHORT, isPriced, whenPriced } from "@/features/video-studio/credit-notes";
import { scriptFromLibrary, talkingApi, type LibraryEntry } from "@/features/video-studio/talking-api";
import {
  addScripts, assign, assignmentFor, batchItems, batchSettled, cloneAction, draftAfterBatch, editingCta, decodeDraft, displayTitle, draftKey, durationLabel, emptyDraft, encodeDraft,
  MAX_SCRIPTS, PARALLEL_LIMIT, planEntry, previousBatchLine, problems, removeScript, resultBoxes, rotate, rotationCounts, scriptChars, scriptSeconds, summary, switchDrive, switchMode,
  voiceFromPersona, withAvatar, withPersona, withVoice, type Assignment, type TalkingBatch, type TalkingDraft, type TalkingScript,
} from "@/features/video-studio/talking-batch";
import { mediaUrl } from "@/lib/api/base-url";
import { ApiError } from "@/lib/api/api-error";
import { Dialog, Empty } from "./studio-primitives";
import { ShortOfCredits } from "./studio-content";
import { VoicePicker } from "./voice-picker";
import { avatarLabel, PresenterPicker, type PresenterChoice } from "./presenter-picker";
import baseStyles from "./video-studio.module.css";
import styles from "./talking-studio.module.css";

type Props = {
  userId: string; workspaceId: string;
  avatars: VideoAvatar[]; voices: VideoVoice[]; libraryLoading: boolean; libraryError: string; onReloadLibrary: () => void;
  uploadAudio: (file: File) => Promise<{ id: string }>;
  library: ReturnType<typeof useVideoLibrary>; clones: ReturnType<typeof useVoiceClones>;
  price: number | null; available?: number; enforced?: boolean;
  notify: (text: string, tone?: "info" | "success" | "error") => void;
  stepBar: React.ReactNode; onBack: () => void; onWriting: () => void;
};
type Picker = { kind: "presenter" | "voice"; target: string } | null;
const STEP_TITLES = ["文案", "数字人", "音色", "生成"] as const;
const uid = () => crypto.randomUUID();

export function TalkingStudio(props: Props) {
  const { userId, workspaceId, avatars, voices, notify } = props;
  const router = useRouter();
  const search = useSearchParams();
  const api = useMemo(() => talkingApi(workspaceId), [workspaceId]);
  const storageKey = draftKey(userId, workspaceId);
  const [draft, setDraftState] = useState<TalkingDraft>(emptyDraft);
  const [restored, setRestored] = useState(false);
  const personaStore = usePersonas(workspaceId);
  const personas: VideoPersona[] = personaStore.personas;
  const [drawer, setDrawer] = useState<{ kind: "avatar" | "persona" | "voice"; target: string } | null>(null);
  const [picker, setPicker] = useState<Picker>(null);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [manualText, setManualText] = useState("");
  const [manualOpen, setManualOpen] = useState(false);
  const [missing, setMissing] = useState(0);
  const [uploading, setUploading] = useState(0);
  const [batch, setBatch] = useState<TalkingBatch>();
  /** A4：带新文案进来时，还在生成的上一批只在顶部提示一行。 */
  const [previous, setPrevious] = useState<TalkingBatch>();
  const [rotationOpen, setRotationOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [retrying, setRetrying] = useState<string[]>([]);
  const [playing, setPlaying] = useState("");
  const player = useRef<HTMLAudioElement | null>(null);
  const resultsRef = useRef<HTMLElement>(null);

  const setDraft = useCallback((next: TalkingDraft | ((current: TalkingDraft) => TalkingDraft)) => {
    setDraftState(current => {
      const value = typeof next === "function" ? next(current) : next;
      try { sessionStorage.setItem(storageKey, encodeDraft(value)); } catch { /* 草稿只是方便，存不了也能用 */ }
      return value;
    });
  }, [storageKey]);

  // 打开时（规则见 planEntry）：带 ?scripts= 就直接配置新一批，上一批只在顶部提示；带 ?batch= 显示那一批；
  // 都没有时找回最近一个还在生成的批次。
  useEffect(() => {
    let active = true;
    const flow = parseFlowParams(new URLSearchParams(search.toString()));
    const hasScripts = !!flow.scripts?.length;
    void (async () => {
      let stored: TalkingDraft | undefined;
      try { stored = decodeDraft(sessionStorage.getItem(storageKey)); } catch { stored = undefined; }
      const [latestOpen, page] = await Promise.all([
        flow.batch ? Promise.resolve(null) : api.latestOpenBatch().catch(() => null),
        hasScripts ? api.libraryByIds(flow.scripts!).catch(() => { if (active) notify("文案库暂时读不到，可以稍后从文案库重新选择", "error"); return null; }) : Promise.resolve(null),
      ]);
      const plan = planEntry({ stored, hasScripts, batchParam: flow.batch, latestOpen });
      let next = plan.draft;
      if (page) {
        next = addScripts(next.drive === "audio" ? switchDrive(next, "text") : next, page.items.map(scriptFromLibrary));
        if (active) setMissing(page.missing_ids?.length ?? 0);
      }
      if (!active) return;
      setDraft(next);
      if (plan.show) {
        try { const view = await api.status(plan.show); if (active) setBatch(view); } catch { /* 批次读不到时不打扰 */ }
      }
      if (!active) return;
      setRestored(true);
      if (plan.previous) {
        try { const view = await api.status(plan.previous); if (active) setPrevious(view); } catch { /* 读不到就不提示 */ }
      }
    })();
    return () => { active = false; };
    // 只在进入页面时执行一次。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 结果区轮询：还有没完成的就每 4 秒问一次后端（后端同时会启动排到的条目）。
  useEffect(() => {
    if (!batch || batchSettled(batch)) return;
    const timer = setInterval(() => { void api.status(batch.batch.id).then(setBatch).catch(() => undefined); }, 4000);
    return () => clearInterval(timer);
  }, [api, batch]);
  // 顶部「上一批还在生成」的进度：慢一点刷新即可（真正推进由批次页和后端巡检负责）。
  useEffect(() => {
    if (!previous || batch || batchSettled(previous)) return;
    const timer = setInterval(() => { void api.status(previous.batch.id).then(setPrevious).catch(() => undefined); }, 10000);
    return () => clearInterval(timer);
  }, [api, previous, batch]);
  useEffect(() => () => { player.current?.pause(); }, []);

  const avatarIds = useMemo(() => new Set(avatars.filter(a => a.ready).map(a => a.id)), [avatars]);
  const usableVoices = useMemo(() => voices.filter(v => v.available !== false), [voices]);
  const voiceIds = useMemo(() => new Set(usableVoices.map(v => v.id)), [usableVoices]);
  const issues = problems(draft, { avatarIds, voiceIds });
  const totals = summary(draft, props.price);
  const short = !!props.enforced && totals.credits !== null && (props.available ?? 0) < totals.credits;
  const textDrive = draft.drive === "text";
  const avatarOf = (id?: string) => avatars.find(a => a.id === id);
  const voiceOf = (id?: string) => voices.find(v => v.id === id);
  const personaOf = (id?: string) => personas.find(p => p.id === id);
  const goStep = (step: TalkingDraft["step"]) => setDraft(current => ({ ...current, step: !textDrive && step === 3 ? (current.step < 3 ? 4 : 2) : step }));
  const stepDone = (step: 1 | 2 | 3) => !issues.some(problem => problem.step === step);

  const previewVoice = (voice: VideoVoice) => {
    player.current?.pause();
    if (playing === voice.id) { setPlaying(""); return; }
    if (!voice.preview_url) { notify("这个音色的试听还在准备"); return; }
    const audio = new Audio(mediaUrl(voice.preview_url));
    player.current = audio;
    audio.onended = () => setPlaying("");
    audio.onerror = () => { setPlaying(""); notify("试听暂不可用，请稍后重试"); };
    setPlaying(voice.id);
    void audio.play().catch(() => setPlaying(""));
  };

  const addManual = () => {
    const text = manualText.trim();
    if (!text) return;
    setDraft(current => addScripts(current, [{ key: `manual:${uid()}`, source: "manual", title: "", body: "", script: text }]));
    setManualText(""); setManualOpen(false);
  };

  const uploadFiles = (files: FileList | null) => {
    const list = Array.from(files ?? []).slice(0, MAX_SCRIPTS - draft.scripts.length);
    for (const file of list) {
      if (!file.type.startsWith("audio/")) { notify(`${file.name} 不是音频文件`); continue; }
      if (file.size > 50 * 1024 * 1024) { notify(`${file.name} 超过 50 MB`); continue; }
      const key = `audio:${uid()}`;
      const url = URL.createObjectURL(file);
      const probe = new Audio(url);
      probe.onloadedmetadata = () => { const seconds = probe.duration; URL.revokeObjectURL(url); if (Number.isFinite(seconds)) setDraft(current => ({ ...current, scripts: current.scripts.map(s => s.key === key ? { ...s, audioSeconds: seconds } : s) })); };
      setDraft(current => addScripts(current.drive === "audio" ? current : switchDrive(current, "audio"), [{ key, source: "audio", title: "", body: "", script: "", audioName: file.name }]));
      setUploading(count => count + 1);
      void props.uploadAudio(file)
        .then(uploaded => setDraft(current => ({ ...current, scripts: current.scripts.map(s => s.key === key ? { ...s, audioId: uploaded.id } : s) })))
        .catch(() => { notify(`${file.name} 上传失败，请重新选择`, "error"); setDraft(current => removeScript(current, key)); })
        .finally(() => setUploading(count => count - 1));
    }
  };

  // 连点两次时第二次点击在重新渲染之前就到了：用 ref 同步加锁；提交编号按「同一份内容」复用，
  // 内容不变就永远是同一个编号（后端据此只建一个批次），内容变了才换新编号。
  const inFlight = useRef(false);
  const pending = useRef<{ id: string; content: string } | undefined>(undefined);
  const generate = async () => {
    if (inFlight.current || issues.length) return;
    inFlight.current = true;
    const content = JSON.stringify(batchItems(draft));
    const requestId = pending.current?.content === content ? pending.current.id : draft.requestId ?? uid();
    pending.current = { id: requestId, content };
    const pinned = { ...draft, requestId };
    setDraft(pinned);
    setSubmitting(true); setSubmitError("");
    try {
      const view = await api.submit(pinned);
      setBatch(view);
      setPrevious(undefined);
      pending.current = undefined;
      setDraft(current => ({ ...current, requestId: undefined, submittedBatchId: view.batch.id }));
      router.replace(`/video-studio/create?batch=${encodeURIComponent(view.batch.id)}`, { scroll: false });
      requestAnimationFrame(() => resultsRef.current?.scrollIntoView({ block: "start", behavior: "smooth" }));
    } catch (error) {
      // 4xx 是确定的拒绝（例如积分不足），说明原因；其他情况结果未知，同一个提交编号再点一次只会找回原批次。
      if (error instanceof ApiError && error.status && error.status < 500) { pending.current = undefined; setSubmitError(error.message); setDraft(current => ({ ...current, requestId: undefined })); }
      else setSubmitError(`网络不稳定，提交结果还没确认。再点一次「确认生成」会找回刚才的批次${whenPriced(props.price, "，不会重复扣积分")}。`);
    } finally { inFlight.current = false; setSubmitting(false); }
  };

  const retry = async (itemId: string) => {
    if (!batch || retrying.includes(itemId)) return;
    setRetrying(ids => [...ids, itemId]);
    try { setBatch(await api.retry(itemId)); }
    catch (error) { notify(error instanceof Error && error.message ? error.message : "重试没有提交成功，请稍后再试", "error"); }
    finally { setRetrying(ids => ids.filter(id => id !== itemId)); }
  };

  const [swapItem, setSwapItem] = useState<string>();
  const swap = async (itemId: string, choice: PresenterChoice) => {
    const item = batch?.batch.items.find(row => row.id === itemId);
    if (!item) return;
    setSwapItem(undefined);
    setRetrying(ids => [...ids, itemId]);
    const change = choice.kind === "persona"
      ? { avatar_id: choice.persona.avatar_id, persona_id: choice.persona.id, ...(item.drive_mode === "text" ? { voice_id: choice.persona.voice_id } : {}) }
      : { avatar_id: choice.avatar.id, persona_id: null };
    try { setBatch(await api.swapAndRetry(itemId, item.version, change)); notify("已换数字人，这一条重新生成中", "success"); }
    catch (error) { notify(error instanceof Error && error.message ? error.message : "没有换成功，请刷新后再试", "error"); void api.status(batch!.batch.id).then(setBatch).catch(() => undefined); }
    finally { setRetrying(ids => ids.filter(id => id !== itemId)); }
  };

  const check = async (itemId: string) => {
    if (!batch || retrying.includes(itemId)) return;
    setRetrying(ids => [...ids, itemId]);
    try { const view = await api.check(itemId); setBatch(view); notify(view.notice || "已重新查询这条的结果", view.notice ? "info" : "success"); }
    catch { notify("查询没有成功，请稍后再试", "error"); }
    finally { setRetrying(ids => ids.filter(id => id !== itemId)); }
  };

  // 「再做一批」：生成过的草稿清空；还没生成的稿（从文案库带进来的）保留。离开的那批还在生成就在顶部留一行。
  const startOver = () => {
    const next = draftAfterBatch(draft);
    if (batch && !batchSettled(batch)) setPrevious(batch);
    setBatch(undefined); setDraft(next); setSubmitError("");
    const docs = next.scripts.map(script => script.documentId).filter((id): id is string => !!id);
    router.replace(docs.length ? voiceHref(docs) : "/video-studio/create", { scroll: false });
  };
  // 顶部「查看」：看上一批，新选的稿留在草稿里（地址里也保留 ?scripts=，刷新不丢）。
  const viewPrevious = () => {
    if (!previous) return;
    const docs = draft.scripts.map(script => script.documentId).filter((id): id is string => !!id);
    setBatch(previous); setPrevious(undefined);
    router.replace(`/video-studio/create?batch=${encodeURIComponent(previous.batch.id)}${docs.length ? `&scripts=${docs.join(",")}` : ""}`, { scroll: false });
  };
  const priced = isPriced(props.price);
  const clone = cloneAction(props.clones.config);

  const applyPresenter = (target: string, next: (current: Assignment) => Assignment) => setDraft(current => assign(current, target, next));

  // ---- 渲染 ----
  const stepHeader = (step: 1 | 2 | 3 | 4, note: string) => {
    const active = draft.step === step;
    const done = step < 4 && step !== draft.step && stepDone(step as 1 | 2 | 3) && draft.scripts.length > 0;
    const skipped = step === 3 && !textDrive;
    return <header className={styles.stepHead}>
      <span className={`${styles.stepNo} ${active ? styles.stepNoActive : done ? styles.stepNoDone : ""}`}>{done && !active ? <Check size={13} /> : step}</span>
      <div><h2>{STEP_TITLES[step - 1]}</h2><p>{skipped ? "音频驱动不需要选音色" : note}</p></div>
      {!active && !skipped && <button type="button" className={styles.quietButton} onClick={() => goStep(step)}>{done ? "修改" : "展开"}</button>}
    </header>;
  };

  const scriptLine = (script: TalkingScript, index: number) => <li key={script.key} className={styles.scriptRow}>
    <span className={styles.scriptIndex}>{index + 1}</span>
    <div className={styles.scriptText}>
      <b>{displayTitle(script)}</b>
      <small>{script.source === "audio" ? (script.audioId ? `音频 · ${script.audioSeconds ? durationLabel(script.audioSeconds) : "已上传"}` : "正在上传…") : `${scriptChars(script)} 字 · 约 ${durationLabel(scriptSeconds(script))}${script.source === "library" ? " · 来自文案库" : ""}`}</small>
      {script.source !== "audio" && <p>{script.script}</p>}
    </div>
    <button type="button" className={styles.iconButton} aria-label={`移除第 ${index + 1} 条`} onClick={() => setDraft(current => removeScript(current, script.key))}><Trash2 size={15} /></button>
  </li>;

  const presenterCell = (target: string, row: Assignment) => {
    const persona = personaOf(row.personaId);
    const avatar = avatarOf(row.avatarId);
    return <button type="button" className={styles.presenterCell} onClick={() => setPicker({ kind: "presenter", target })}>
      {avatar ? <img src={mediaUrl(avatar.cover_url || undefined)} alt="" /> : <span className={styles.presenterEmpty} />}
      <span><b>{persona ? persona.name : avatar ? avatarLabel(avatar) : "选择数字人"}</b><small>{persona ? "固定形象" : avatar ? (avatar.source === "self_owned" ? "我的形象" : "公共形象") : "未选择"}</small></span>
    </button>;
  };
  const voiceCell = (target: string, row: Assignment) => {
    const voice = voiceOf(row.voiceId);
    const fromPersona = voiceFromPersona(row, personas);
    return <div className={styles.voiceCell}>
      <button type="button" className={styles.voiceName} onClick={() => setPicker({ kind: "voice", target })}><b>{voice?.name ?? "选择音色"}</b><small>{fromPersona ? "已随固定形象带入，可更换" : voice ? [voice.gender !== "未知" ? `${voice.gender}声` : "", voice.language || voice.tag].filter(Boolean).join(" · ") : "未选择"}</small></button>
      {voice?.preview_url && <button type="button" className={styles.iconButton} aria-label={`${playing === voice.id ? "停止" : "试听"}${voice.name}`} onClick={() => previewVoice(voice)}>{playing === voice.id ? <Pause size={14} /> : <Play size={14} />}</button>}
    </div>;
  };

  const assignTable = (withVoiceColumn: boolean) => <div className={styles.assignTable} data-cols={withVoiceColumn ? 3 : 2} role="table" aria-label="每条稿的数字人与音色">
    <div className={styles.assignHead} role="row"><span role="columnheader">稿</span><span role="columnheader">数字人</span>{withVoiceColumn && <span role="columnheader">音色</span>}</div>
    {draft.scripts.map((script, index) => { const row = assignmentFor(draft, script.key); return <div key={script.key} className={styles.assignRow} role="row">
      <div role="cell" className={styles.assignScript}><span className={styles.scriptIndex}>{index + 1}</span><span><b>{displayTitle(script)}</b><small>{script.source === "audio" ? "音频" : `${scriptChars(script)} 字 · 约 ${durationLabel(scriptSeconds(script))}`}</small></span></div>
      <div role="cell">{presenterCell(script.key, row)}</div>
      {withVoiceColumn && <div role="cell">{voiceCell(script.key, row)}</div>}
    </div>; })}
  </div>;

  const shared = draft.shared;
  const stepOne = <section className={`${styles.step} ${draft.step === 1 ? styles.stepActive : ""}`} aria-label="第 1 步 文案">
    {stepHeader(1, draft.scripts.length ? `${draft.scripts.length} 条${textDrive ? "稿" : "音频"} · 共约 ${durationLabel(totals.seconds)}` : "从文案库选一条或多条稿，或上传音频")}
    {draft.step === 1 && <div className={styles.stepBody}>
      <div className={styles.segmented} role="group" aria-label="驱动方式">
        <button type="button" aria-pressed={textDrive} onClick={() => setDraft(current => switchDrive(current, "text"))}><FileText size={15} />文本驱动</button>
        <button type="button" aria-pressed={!textDrive} onClick={() => setDraft(current => switchDrive(current, "audio"))}><AudioLines size={15} />音频驱动</button>
      </div>
      {missing > 0 && <p className={styles.warn}>有 {missing} 条文案已删除，已跳过。</p>}
      {draft.scripts.length > 0 && <ol className={styles.scriptList}>{draft.scripts.map(scriptLine)}</ol>}
      {textDrive ? <>
        {manualOpen && <div className={styles.manual}><textarea aria-label="手动输入口播稿" value={manualText} maxLength={3000} placeholder="粘贴或输入一条口播稿，数字人会照着念" onChange={event => setManualText(event.target.value)} /><div><small>{scriptStats(manualText).label}</small><button type="button" className={baseStyles.outlineButton} onClick={() => { setManualOpen(false); setManualText(""); }}>取消</button><button type="button" className={baseStyles.primaryButton} disabled={!manualText.trim()} onClick={addManual}>加入这条</button></div></div>}
        <div className={styles.actions}>
          <button type="button" className={baseStyles.outlineButton} disabled={draft.scripts.length >= MAX_SCRIPTS} onClick={() => setLibraryOpen(true)}><BookOpenText size={15} />从文案库选择</button>
          {!manualOpen && <button type="button" className={baseStyles.outlineButton} disabled={draft.scripts.length >= MAX_SCRIPTS} onClick={() => setManualOpen(true)}><Plus size={15} />手动输入一条</button>}
          <button type="button" className={styles.quietButton} onClick={props.onWriting}><Flame size={14} />去写爆款文案</button>
        </div>
      </> : <div className={styles.actions}>
        <label className={baseStyles.outlineButton}><Upload size={15} />上传音频<input type="file" accept="audio/*" multiple hidden onChange={event => { uploadFiles(event.target.files); event.target.value = ""; }} /></label>
        <small className={styles.muted}>每段音频生成一条口播 · MP3、WAV、M4A · 单个 50 MB 以内</small>
      </div>}
      <footer className={styles.stepFoot}><small>{draft.scripts.length ? `最多 ${MAX_SCRIPTS} 条，同时生成 ${PARALLEL_LIMIT} 条，其余排队` : ""}</small><button type="button" className={baseStyles.primaryButton} disabled={!stepDone(1)} onClick={() => goStep(2)}>下一步：选数字人</button></footer>
    </div>}
  </section>;

  const stepTwo = <section className={`${styles.step} ${draft.step === 2 ? styles.stepActive : ""}`} aria-label="第 2 步 数字人">
    {stepHeader(2, draft.scripts.length > 1 ? (draft.mode === "same" ? "所有稿用同一个数字人" : draft.rotation ? `${draft.rotation.length} 个固定形象轮流` : "每条单独选数字人") + (totals.presenters ? ` · ${totals.presenters} 个数字人` : "") : (avatarOf(shared.avatarId) ? (personaOf(shared.personaId)?.name ?? avatarLabel(avatarOf(shared.avatarId)!)) : "选择出镜的数字人"))}
    {draft.step === 2 && <div className={styles.stepBody}>
      {draft.scripts.length > 1 && <div className={styles.segmented} role="group" aria-label="数字人设置方式">
        <button type="button" aria-pressed={draft.mode === "same"} onClick={() => setDraft(current => switchMode(current, "same"))}>所有稿用同一个</button>
        <button type="button" aria-pressed={draft.mode === "each" && !draft.rotation} onClick={() => setDraft(current => switchMode(current, "each"))}>每条单独选</button>
        <button type="button" aria-pressed={!!draft.rotation} onClick={() => setRotationOpen(true)}>固定形象轮流</button>
      </div>}
      {draft.rotation && draft.scripts.length > 1 && <p className={styles.rotationLine}>
        <span>{draft.rotation.length} 个固定形象轮流：{rotationCounts(draft).map(row => `${personaOf(row.personaId)?.name ?? "固定形象"} ${row.count} 条`).join(" · ")}</span>
        <button type="button" className={styles.linkButton} onClick={() => setRotationOpen(true)}>重新选择</button>
      </p>}
      {draft.mode === "same" || draft.scripts.length <= 1 ? <div className={styles.sharedPick}>
        {presenterCell("all", draft.mode === "same" ? shared : assignmentFor(draft, draft.scripts[0]?.key ?? ""))}
        <p className={styles.muted}>{draft.scripts.length > 1 ? `一次设置，${draft.scripts.length} 条稿都用这个数字人。` : "选固定形象会同时带上它的声音。"}</p>
      </div> : <>{assignTable(false)}{!draft.rotation && <button type="button" className={styles.linkButton} onClick={() => { const first = assignmentFor(draft, draft.scripts[0].key); setDraft(current => assign(current, "all", () => ({ ...first }))); notify(`已把第 1 条的数字人${textDrive ? "和音色" : ""}用到全部 ${draft.scripts.length} 条`, "success"); }}><CopyCheck size={14} />把第 1 条的设置用到全部</button>}</>}
      {props.libraryError && <p className={styles.warn}>{props.libraryError}<button type="button" className={styles.quietButton} onClick={props.onReloadLibrary}>重新读取</button></p>}
      <footer className={styles.stepFoot}><small /><button type="button" className={baseStyles.primaryButton} disabled={!stepDone(2)} onClick={() => goStep(textDrive ? 3 : 4)}>{textDrive ? "下一步：选音色" : "下一步：确认生成"}</button></footer>
    </div>}
  </section>;

  const stepThree = <section className={`${styles.step} ${draft.step === 3 ? styles.stepActive : ""} ${!textDrive ? styles.stepSkipped : ""}`} aria-label="第 3 步 音色">
    {stepHeader(3, draft.mode === "same" || draft.scripts.length <= 1 ? (voiceOf(shared.voiceId)?.name ?? "选择数字人的声音") : "每条稿的音色")}
    {draft.step === 3 && textDrive && <div className={styles.stepBody}>
      {draft.mode === "same" || draft.scripts.length <= 1 ? <div className={styles.sharedPick}>{voiceCell("all", draft.mode === "same" ? shared : assignmentFor(draft, draft.scripts[0]?.key ?? ""))}</div> : assignTable(true)}
      <div className={styles.actions}><button type="button" className={styles.quietButton} aria-disabled={!clone.available} data-unavailable={!clone.available || undefined} title={clone.hint || undefined} onClick={() => { if (clone.available) setDrawer({ kind: "voice", target: "all" }); }}><Plus size={14} />{clone.label}</button>{!clone.available && <small className={styles.muted}>{clone.hint}</small>}</div>
      <footer className={styles.stepFoot}><small /><button type="button" className={baseStyles.primaryButton} disabled={!stepDone(3)} onClick={() => goStep(4)}>下一步：确认生成</button></footer>
    </div>}
  </section>;

  const stepFour = <section className={`${styles.step} ${draft.step === 4 ? styles.stepActive : ""}`} aria-label="第 4 步 生成">
    {stepHeader(4, draft.scripts.length ? `共 ${totals.count} 条` : "确认后并行生成")}
    {draft.step === 4 && <div className={styles.stepBody}>
      <dl className={styles.summary}>
        <div><dt>条数</dt><dd>{totals.count} 条</dd></div>
        <div><dt>预计积分</dt><dd>{creditPhrase(totals.credits)}</dd></div>
        <div><dt>预计耗时</dt><dd>{totals.minutes[0]}–{totals.minutes[1]} 分钟</dd></div>
        <div><dt>数字人</dt><dd>{totals.presenters} 个</dd></div>
      </dl>
      <p className={styles.muted}>每条单独生成，同时最多 {PARALLEL_LIMIT} 条{totals.queued ? `，其余 ${totals.queued} 条排队` : ""}。某一条失败不影响其他条，{whenPriced(totals.credits, "失败的不扣积分，")}可以单独重试。{props.available !== undefined ? ` 当前可用 ${props.available.toLocaleString("zh-CN")} 积分。` : ""}</p>
      {draft.scripts.length > 1 && assignTable(textDrive)}
      {issues.length > 0 && <ul className={styles.issues}>{issues.map(issue => <li key={issue.text}><button type="button" onClick={() => goStep(issue.step)}>第 {issue.step} 步：{issue.text}</button></li>)}</ul>}
      {submitError && <p className={styles.warn} role="alert">{submitError}</p>}
      {short && <ShortOfCredits credits={totals.credits} />}
      <footer className={styles.stepFoot}><small /><button type="button" className={`${baseStyles.primaryButton} ${styles.generate}`} aria-busy={submitting} disabled={submitting || issues.length > 0 || short || uploading > 0} onClick={() => void generate()}>{submitting ? <><span className={styles.spinner} aria-hidden="true" />正在提交…</> : submitError && !short ? `再次确认${whenPriced(totals.credits, "（不会重复扣费）")}` : `确认生成 ${totals.count} 条 · ${isPriced(totals.credits) ? `${totals.credits} 积分` : FREE_TRIAL_SHORT}`}</button></footer>
    </div>}
  </section>;

  const boxes = batch ? resultBoxes(batch, stage => generationProgress({ status: "running", stage, kind: "lipsync" }).title, priced) : [];
  const doneCount = boxes.filter(box => box.state === "done").length;
  const cta = editingCta(boxes, !!batch && batchSettled(batch));
  const results = batch && <section ref={resultsRef} className={styles.results} aria-label="生成结果">
    <header className={styles.resultsHead}>
      <div><h2>生成结果</h2><p>{batchSettled(batch) ? `${doneCount} 条完成${boxes.length - doneCount ? `，${boxes.length - doneCount} 条失败` : ""}` : `共 ${boxes.length} 条 · 已完成 ${doneCount} 条 · 关掉页面也会继续生成`}</p></div>
      <div className={styles.resultsActions}>
        <button type="button" className={baseStyles.outlineButton} onClick={startOver}>{!draft.submittedBatchId && draft.scripts.length ? `再做一批（已选 ${draft.scripts.length} 条）` : "再做一批"}</button>
        <button type="button" className={baseStyles.primaryButton} disabled={cta.disabled} onClick={() => router.push(editingHref(batch.batch.id))}>{cta.label}</button>
        {cta.note && <small className={styles.ctaNote}>{cta.note}</small>}
      </div>
    </header>
    <ol className={`${styles.resultGrid} ${boxes.length === 1 ? styles.resultSingle : ""}`}>{boxes.map((box, index) => {
      const item = batch.batch.items[index];
      const cover = avatarOf(item?.avatar_id ?? undefined)?.cover_url;
      const who = [personaOf(item?.persona_id ?? undefined)?.name ?? (avatarOf(item?.avatar_id ?? undefined) ? avatarLabel(avatarOf(item?.avatar_id ?? undefined)!) : ""), item?.drive_mode === "audio" ? "上传音频" : voiceOf(item?.voice_id ?? undefined)?.name ?? ""].filter(Boolean).join(" · ");
      return <li key={box.id} className={styles.resultBox} data-state={box.state}>
        <div className={styles.resultMedia}>
          {box.state === "done" && box.videoUrl ? <ResultVideo src={mediaUrl(box.videoUrl) ?? box.videoUrl} poster={cover ? mediaUrl(cover) : undefined} label={`${box.title} 口播视频`} /> : <>{cover && <img src={mediaUrl(cover)} alt="" aria-hidden="true" />}<span className={styles.resultStatus}>{box.state === "failed" ? <X size={16} /> : null}{box.label}</span>{box.state === "running" && <span className={styles.progressLine} aria-hidden="true" />}</>}
        </div>
        <div className={styles.resultMeta}>
          <b><span>{index + 1}</span>{box.title}</b>
          {who && <small className={styles.who}>{who}</small>}
          {box.state === "failed" && box.error && <small className={styles.failText}>{box.error}</small>}
          {box.note && <small className={styles.noteText}>{box.note}</small>}
          <div>
            {box.state === "done" && box.videoUrl && <a className={styles.quietButton} href={mediaUrl(box.videoUrl)} download><Download size={14} />下载</a>}
            {box.canCheck && <button type="button" className={styles.quietButton} disabled={retrying.includes(box.id)} onClick={() => void check(box.id)}><Search size={14} />{retrying.includes(box.id) ? "正在查询" : "查询结果"}</button>}
            {box.state === "failed" && box.canRetry && <button type="button" className={styles.quietButton} disabled={retrying.includes(box.id)} onClick={() => setSwapItem(box.id)}><UsersRound size={14} />换数字人</button>}
            {box.state === "failed" && box.canRetry && <button type="button" className={styles.quietButton} disabled={retrying.includes(box.id)} onClick={() => void retry(box.id)}><RotateCcw size={14} />{retrying.includes(box.id) ? "正在重试" : "重试这一条"}</button>}
          </div>
        </div>
      </li>;
    })}</ol>
  </section>;

  // 有批次时：结果在最上面，四步收成一行本批摘要；点「再做一批」才清空重来。
  const batchNames = batch ? [...new Set(batch.batch.items.map(item => personaOf(item.persona_id ?? undefined)?.name ?? (avatarOf(item.avatar_id ?? undefined) ? avatarLabel(avatarOf(item.avatar_id ?? undefined)!).split(" · ")[0] : "")).filter(Boolean))] : [];
  const batchState = !batch ? "" : batchSettled(batch) ? (boxes.length - doneCount ? `${doneCount} 条完成 · ${boxes.length - doneCount} 条失败` : "已完成") : `生成中 · 已完成 ${doneCount} 条`;
  const batchLine = batch && <section className={styles.batchLine} aria-label="本批设置">
    <span className={styles.stepNo}><Check size={13} /></span>
    <p><b>本批：{boxes.length} 条</b>{batchNames.length > 0 && <> · {batchNames.join(" / ")}</>} · {batchState}</p>
  </section>;
  const pickerTarget = picker?.target ?? "all";
  const pickerRow = pickerTarget === "all" ? (draft.mode === "same" ? shared : assignmentFor(draft, draft.scripts[0]?.key ?? "")) : assignmentFor(draft, pickerTarget);
  const drawerRow = drawer ? (drawer.target === "all" ? (draft.mode === "same" ? shared : assignmentFor(draft, draft.scripts[0]?.key ?? "")) : assignmentFor(draft, drawer.target)) : {};
  const pickerTitle = pickerTarget === "all" || draft.mode === "same" ? "选择数字人" : `第 ${draft.scripts.findIndex(s => s.key === pickerTarget) + 1} 条的数字人`;

  return <main className={styles.page}>
    <div className={styles.inner}>
      {props.stepBar}
      <header className={styles.pageHead}>
        <Link href="/video-studio" className={styles.back} aria-label="返回视频空间" onClick={event => { event.preventDefault(); props.onBack(); }}><ArrowLeft size={18} /></Link>
        <div><h1>口播</h1><p>选好文案、数字人和音色，一次生成多条口播视频。</p></div>
      </header>
      {!restored ? <div className={styles.loading} role="status">正在载入…</div> : batch ? <>{batchLine}{results}</> : <>
        {previous && <p className={styles.previousLine} role="status"><span>{previousBatchLine(previous)}</span><a href={`/video-studio/create?batch=${encodeURIComponent(previous.batch.id)}`} className={styles.linkButton} onClick={event => { event.preventDefault(); viewPrevious(); }}>查看</a></p>}
        <div className={styles.steps}>{stepOne}{stepTwo}{stepThree}{stepFour}</div>
      </>}
    </div>
    {libraryOpen && <ScriptLibraryDialog api={api} chosen={new Set(draft.scripts.map(s => s.documentId).filter((id): id is string => !!id))} room={MAX_SCRIPTS - draft.scripts.length} onClose={() => setLibraryOpen(false)} onAdd={entries => { setDraft(current => addScripts(current.drive === "audio" ? switchDrive(current, "text") : current, entries.map(scriptFromLibrary))); setLibraryOpen(false); }} />}
    {picker?.kind === "presenter" && <PresenterPicker title={pickerTitle} personas={personas} avatars={avatars} voices={voices} selected={pickerRow}
      onClose={() => setPicker(null)}
      onApply={choice => { applyPresenter(pickerTarget, current => choice.kind === "persona" ? withPersona(choice.persona) : withAvatar(current, choice.avatar.id)); setPicker(null); }}
      onCreatePersona={() => setDrawer({ kind: "persona", target: pickerTarget })} onCreateAvatar={() => setDrawer({ kind: "avatar", target: pickerTarget })} jobs={props.library.jobs} />}
    {swapItem && batch && (() => { const item = batch.batch.items.find(row => row.id === swapItem); return item ? <PresenterPicker title={`换第 ${item.position + 1} 条的数字人`} personas={personas} avatars={avatars} voices={voices} jobs={props.library.jobs} selected={{ personaId: item.persona_id ?? undefined, avatarId: item.avatar_id ?? undefined }} onClose={() => setSwapItem(undefined)} onApply={choice => void swap(swapItem, choice)} onCreatePersona={() => setDrawer({ kind: "persona", target: "all" })} onCreateAvatar={() => setDrawer({ kind: "avatar", target: "all" })} /> : null; })()}
    {picker?.kind === "voice" && <VoicePickerFor voices={usableVoices} row={pickerRow} playing={playing} onPreview={previewVoice} onClose={() => setPicker(null)} onApply={voiceId => { applyPresenter(pickerTarget, current => withVoice(current, voiceId)); setPicker(null); }} onClone={() => { if (clone.available) setDrawer({ kind: "voice", target: pickerTarget }); }} clone={clone} />}
    {rotationOpen && <RotationDialog personas={personas} voices={voices} scripts={draft.scripts.length} initial={draft.rotation?.map(row => row.personaId ?? "") ?? []}
      onClose={() => setRotationOpen(false)}
      onCreate={() => { setRotationOpen(false); setDrawer({ kind: "persona", target: "all" }); }}
      onApply={chosen => { setDraft(current => rotate(current, chosen)); setRotationOpen(false); notify(`已在 ${chosen.length} 个固定形象里轮流分配 ${draft.scripts.length} 条稿`, "success"); }} />}
    <AvatarCreateDrawer open={drawer?.kind === "avatar"} onClose={() => setDrawer(null)} workspaceId={workspaceId} userId={userId} library={props.library}
      onCreated={() => notify("形象开始定制了，完成后会出现在「我的形象」里。可以先给其他稿选别的数字人。", "success")}
      onReady={avatar => { const target = drawer?.target ?? "all"; applyPresenter(target, current => withAvatar(current, avatar.id)); setDrawer(null); setPicker(null); notify(`已用上新形象「${avatar.name}」`, "success"); }} />
    <PersonaCreateDrawer open={drawer?.kind === "persona"} onClose={() => setDrawer(null)} library={props.library} personas={personaStore}
      initialAvatarId={drawer?.kind === "persona" ? (drawerRow.avatarId ?? "") : ""} initialVoiceId={drawer?.kind === "persona" ? (drawerRow.voiceId ?? "") : ""}
      onCreated={persona => { if (persona.available) { applyPresenter(drawer?.target ?? "all", () => withPersona(persona)); setPicker(null); notify(`已保存并选用固定形象「${persona.name}」`, "success"); } else notify(`已保存固定形象「${persona.name}」：${persona.unavailable_reason || "暂时不能使用"}`); }} />
    <VoiceCloneDrawer open={drawer?.kind === "voice"} onClose={() => setDrawer(null)} workspaceId={workspaceId} clones={props.clones}
      onCreated={() => { void props.library.reload(); notify("声音开始克隆了，完成后会出现在「我的声音」里", "success"); }} onUseSystemVoices={() => setDrawer(null)} />
  </main>;
}

/** 完成的口播：先显示首帧（海报兜底），点播放后才出现原生控件。 */
function ResultVideo({ src, poster, label }: { src: string; poster?: string; label: string }) {
  const [started, setStarted] = useState(false);
  const ref = useRef<HTMLVideoElement>(null);
  return <>
    <video ref={ref} controls={started} playsInline preload="metadata" poster={poster} src={`${src}#t=0.1`} aria-label={label} onEnded={() => setStarted(false)} />
    {!started && <button type="button" className={styles.playOverlay} aria-label={`播放${label}`} onClick={() => { setStarted(true); void ref.current?.play().catch(() => undefined); }}><span><Play size={18} fill="currentColor" /></span></button>}
  </>;
}

function VoicePickerFor({ voices, row, playing, onPreview, onApply, onClose, onClone, clone }: { voices: VideoVoice[]; row: Assignment; playing: string; onPreview: (voice: VideoVoice) => void; onApply: (voiceId: string) => void; onClose: () => void; onClone: () => void; clone: ReturnType<typeof cloneAction> }) {
  const [selected, setSelected] = useState(row.voiceId ?? "");
  return <VoicePicker voices={voices} selectedId={selected} playingId={playing} onSelect={voice => setSelected(voice.id)} onPreview={onPreview} onApply={() => { if (selected) onApply(selected); }} onClose={onClose} onClone={onClone} cloneLabel={clone.label} cloneDisabledHint={clone.available ? undefined : clone.hint} />;
}

/** C10：选几个固定形象，按顺序轮流分给每条稿（12 条 3 个 = 每个 4 条）。 */
function RotationDialog({ personas, voices, scripts, initial, onApply, onClose, onCreate }: { personas: VideoPersona[]; voices: VideoVoice[]; scripts: number; initial: string[]; onApply: (chosen: VideoPersona[]) => void; onClose: () => void; onCreate: () => void }) {
  const usable = personas.filter(persona => persona.available);
  const [picked, setPicked] = useState<string[]>(() => initial.filter(id => usable.some(persona => persona.id === id)));
  const toggle = (id: string) => setPicked(current => current.includes(id) ? current.filter(value => value !== id) : [...current, id]);
  const per = picked.length ? [Math.floor(scripts / picked.length), Math.ceil(scripts / picked.length)] : [0, 0];
  const share = !picked.length ? "" : per[0] === per[1] ? `每个 ${per[0]} 条` : `每个 ${per[0]}–${per[1]} 条`;
  return <Dialog title="在这几个固定形象里轮流分配" className={styles.libraryDialog} onClose={onClose}>
    <p className={styles.muted}>按选择的先后顺序，第 1 条给第一个形象、第 2 条给第二个……轮流分下去，形象自带的声音一起用上。</p>
    <div className={styles.libraryList}>
      {usable.length ? <ul>{usable.map(persona => {
        const order = picked.indexOf(persona.id);
        const voice = voices.find(item => item.id === persona.voice_id);
        return <li key={persona.id}><label className={`${styles.libraryRow} ${styles.rotationRow} ${order >= 0 ? styles.libraryPicked : ""}`}>
          <input type="checkbox" checked={order >= 0} onChange={() => toggle(persona.id)} />
          <span className={styles.libraryOrder}>{order >= 0 ? order + 1 : ""}</span>
          {persona.cover_url ? <img src={mediaUrl(persona.cover_url)} alt="" className={styles.rotationCover} /> : <span className={`${styles.presenterEmpty} ${styles.rotationCover}`} />}
          <span className={styles.libraryText}><b>{persona.name}</b><small>{[persona.avatar_name, voice?.name].filter(Boolean).join(" · ")}</small></span>
        </label></li>;
      })}</ul> : <Empty icon={<UsersRound size={26} />} title="还没有可用的固定形象" description="固定形象 = 数字人 + 声音，保存一次，以后一键选用。" action={<button type="button" className={baseStyles.outlineButton} onClick={onCreate}>保存一个固定形象</button>} />}
    </div>
    <footer className={baseStyles.dialogFooter}><small className={styles.muted}>已选 {picked.length} 个{share ? ` · ${scripts} 条稿，${share}` : ""}</small><button type="button" className={baseStyles.outlineButton} onClick={onClose}>取消</button><button type="button" className={baseStyles.primaryButton} disabled={picked.length < 2} onClick={() => onApply(picked.map(id => usable.find(persona => persona.id === id)!))}>{picked.length < 2 ? "至少选 2 个" : `轮流分配 ${scripts} 条`}</button></footer>
  </Dialog>;
}

/** 文案库多选：显示标题 + 口播稿，按选择顺序加入。 */
function ScriptLibraryDialog({ api, chosen, room, onAdd, onClose }: { api: ReturnType<typeof talkingApi>; chosen: Set<string>; room: number; onAdd: (entries: LibraryEntry[]) => void; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [applied, setApplied] = useState("");
  const [entries, setEntries] = useState<LibraryEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState<LibraryEntry[]>([]);
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => { if (active) setLoading(true); });
    api.library({ q: applied, limit: 50 }).then(page => { if (!active) return; setEntries(page.items); setTotal(page.total); setError(""); })
      .catch(() => { if (active) setError("文案库暂时读不到，请稍后重试。"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [api, applied]);
  const toggle = (entry: LibraryEntry) => setPicked(current => current.some(e => e.id === entry.id) ? current.filter(e => e.id !== entry.id) : current.length >= room ? current : [...current, entry]);
  return <Dialog title="从文案库选择" className={styles.libraryDialog} onClose={onClose}>
    <form className={styles.libraryTools} onSubmit={event => { event.preventDefault(); setApplied(query.trim()); }}>
      <label className={styles.librarySearch}><Search size={15} /><input aria-label="搜索文案" placeholder="搜索标题、正文或口播稿" value={query} onChange={event => setQuery(event.target.value)} /></label>
      <button type="submit" className={baseStyles.outlineButton}>搜索</button>
    </form>
    <div className={styles.libraryList} aria-busy={loading}>
      {loading ? <p className={styles.muted}>正在读取文案库…</p> : error ? <p className={styles.warn}>{error}</p> : entries.length ? <ul>{entries.map(entry => {
        const order = picked.findIndex(e => e.id === entry.id);
        const already = chosen.has(entry.id);
        return <li key={entry.id}><label className={`${styles.libraryRow} ${order >= 0 ? styles.libraryPicked : ""}`}>
          <input type="checkbox" checked={order >= 0 || already} disabled={already || (order < 0 && picked.length >= room)} onChange={() => toggle(entry)} />
          <span className={styles.libraryOrder}>{order >= 0 ? order + 1 : ""}</span>
          <span className={styles.libraryText}><b>{entry.display_title}</b><small>{entry.script_chars} 字 · 约 {durationLabel(entry.script_seconds)}{entry.platform === "douyin" ? " · 抖音" : entry.platform === "xiaohongshu" ? " · 小红书" : ""}{already ? " · 已加入" : ""}</small><p>{entry.script}</p></span>
        </label></li>;
      })}</ul> : <Empty icon={<BookOpenText size={26} />} title={applied ? "没有找到匹配的文案" : "文案库还是空的"} description={applied ? "换个关键词试试。" : "在爆款文案里写好的稿会自动存进文案库。"} />}
    </div>
    <footer className={baseStyles.dialogFooter}><small className={styles.muted}>{total ? `共 ${total} 条 · ` : ""}已选 {picked.length} 条{room < MAX_SCRIPTS ? `，还能加 ${room} 条` : ""}</small><button type="button" className={baseStyles.outlineButton} onClick={onClose}>取消</button><button type="button" className={baseStyles.primaryButton} disabled={!picked.length} onClick={() => onAdd(picked)}>加入 {picked.length || ""} 条</button></footer>
  </Dialog>;
}
