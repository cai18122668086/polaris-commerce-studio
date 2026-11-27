"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, AudioLines, BookOpenText, Check, Download, FileText, Flame, Pause, Play, Plus, RotateCcw, Search, Trash2, Upload, X } from "lucide-react";
import type { VideoAvatar, VideoVoice } from "@/features/video-studio/library";
import { generationProgress } from "@/features/video-studio/generation-progress";
import { editingHref, parseFlowParams } from "@/features/video-studio/flow-params";
import { scriptFromLibrary, talkingApi, type LibraryEntry, type PersonaEntry } from "@/features/video-studio/talking-api";
import {
  addScripts, assign, assignmentFor, batchSettled, decodeDraft, displayTitle, draftKey, durationLabel, emptyDraft, encodeDraft,
  MAX_SCRIPTS, PARALLEL_LIMIT, problems, removeScript, resultBoxes, scriptSeconds, spokenChars, summary, switchDrive, switchMode,
  voiceFromPersona, withAvatar, withPersona, withVoice, type Assignment, type TalkingBatch, type TalkingDraft, type TalkingScript,
} from "@/features/video-studio/talking-batch";
import { mediaUrl } from "@/lib/api/base-url";
import { ApiError } from "@/lib/api/api-error";
import { Dialog, Empty } from "./studio-primitives";
import { ShortOfCredits } from "./studio-content";
import { VoicePicker } from "./voice-picker";
import { avatarLabel, PresenterPicker } from "./presenter-picker";
import baseStyles from "./video-studio.module.css";
import styles from "./talking-studio.module.css";

type Props = {
  userId: string; workspaceId: string;
  avatars: VideoAvatar[]; voices: VideoVoice[]; libraryLoading: boolean; libraryError: string; onReloadLibrary: () => void;
  uploadAudio: (file: File) => Promise<{ id: string }>;
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
  const [personas, setPersonas] = useState<PersonaEntry[]>([]);
  const [picker, setPicker] = useState<Picker>(null);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [manualText, setManualText] = useState("");
  const [manualOpen, setManualOpen] = useState(false);
  const [missing, setMissing] = useState(0);
  const [uploading, setUploading] = useState(0);
  const [batch, setBatch] = useState<TalkingBatch>();
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

  // 打开时：恢复本页草稿 → 带入 ?scripts= 的文案 → 找回进行中的批次（?batch= 或后端最近一个）。
  useEffect(() => {
    let active = true;
    const flow = parseFlowParams(new URLSearchParams(search.toString()));
    void (async () => {
      let base: TalkingDraft | undefined;
      try { base = decodeDraft(sessionStorage.getItem(storageKey)); } catch { base = undefined; }
      let next = base ?? emptyDraft();
      if (flow.scripts?.length) {
        try {
          const page = await api.libraryByIds(flow.scripts);
          next = addScripts(next.drive === "audio" ? switchDrive(next, "text") : next, page.items.map(scriptFromLibrary));
          if (active) setMissing(page.missing_ids?.length ?? 0);
        } catch { if (active) notify("文案库暂时读不到，可以稍后从文案库重新选择", "error"); }
      }
      if (!active) return;
      setDraft(next);
      setRestored(true);
      const batchId = flow.batch ?? await api.latestOpenBatch().catch(() => null);
      if (batchId && active) {
        try { const view = await api.status(batchId); if (active) setBatch(view); } catch { /* 批次读不到时不打扰 */ }
      }
    })();
    void api.personas().then(list => { if (active) setPersonas(list); }).catch(() => undefined);
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

  const generate = async () => {
    if (submitting || issues.length) return;
    const requestId = draft.requestId ?? uid();
    const pinned = { ...draft, requestId };
    setDraft(pinned);
    setSubmitting(true); setSubmitError("");
    try {
      const view = await api.submit(pinned);
      setBatch(view);
      setDraft(current => ({ ...current, requestId: undefined }));
      router.replace(`/video-studio/create?batch=${encodeURIComponent(view.batch.id)}`, { scroll: false });
      requestAnimationFrame(() => resultsRef.current?.scrollIntoView({ block: "start", behavior: "smooth" }));
    } catch (error) {
      // 4xx 是确定的拒绝（例如积分不足），说明原因；其他情况结果未知，同一个提交编号再点一次只会找回原批次。
      if (error instanceof ApiError && error.status && error.status < 500) { setSubmitError(error.message); setDraft(current => ({ ...current, requestId: undefined })); }
      else setSubmitError("网络不稳定，提交结果还没确认。再点一次「确认生成」会找回刚才的批次，不会重复扣积分。");
    } finally { setSubmitting(false); }
  };

  const retry = async (itemId: string) => {
    if (!batch || retrying.includes(itemId)) return;
    setRetrying(ids => [...ids, itemId]);
    try { setBatch(await api.retry(itemId)); }
    catch (error) { notify(error instanceof Error && error.message ? error.message : "重试没有提交成功，请稍后再试", "error"); }
    finally { setRetrying(ids => ids.filter(id => id !== itemId)); }
  };

  const startOver = () => {
    setBatch(undefined); setDraft(emptyDraft()); setSubmitError("");
    router.replace("/video-studio/create", { scroll: false });
  };

  const gotoLibrary = (path: "/video-studio/avatars" | "/video-studio/voices") => {
    // W6 的就地抽屉合入前：草稿已在 sessionStorage，去形象库定制完回到口播页会原样恢复。
    setPicker(null);
    router.push(path);
  };

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
      <small>{script.source === "audio" ? (script.audioId ? `音频 · ${script.audioSeconds ? durationLabel(script.audioSeconds) : "已上传"}` : "正在上传…") : `${spokenChars(script.script)} 字 · 约 ${durationLabel(scriptSeconds(script))}${script.source === "library" ? " · 来自文案库" : ""}`}</small>
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
      <div role="cell" className={styles.assignScript}><span className={styles.scriptIndex}>{index + 1}</span><span><b>{displayTitle(script)}</b><small>{script.source === "audio" ? "音频" : `${spokenChars(script.script)} 字 · 约 ${durationLabel(scriptSeconds(script))}`}</small></span></div>
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
        {manualOpen && <div className={styles.manual}><textarea aria-label="手动输入口播稿" value={manualText} maxLength={3000} placeholder="粘贴或输入一条口播稿，数字人会照着念" onChange={event => setManualText(event.target.value)} /><div><small>{spokenChars(manualText)} 字 · 约 {durationLabel(Math.round(spokenChars(manualText) / 4.8))}</small><button type="button" className={baseStyles.outlineButton} onClick={() => { setManualOpen(false); setManualText(""); }}>取消</button><button type="button" className={baseStyles.primaryButton} disabled={!manualText.trim()} onClick={addManual}>加入这条</button></div></div>}
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
    {stepHeader(2, draft.scripts.length > 1 ? (draft.mode === "same" ? "所有稿用同一个数字人" : "每条单独选数字人") + (totals.presenters ? ` · ${totals.presenters} 个数字人` : "") : (avatarOf(shared.avatarId) ? (personaOf(shared.personaId)?.name ?? avatarLabel(avatarOf(shared.avatarId)!)) : "选择出镜的数字人"))}
    {draft.step === 2 && <div className={styles.stepBody}>
      {draft.scripts.length > 1 && <div className={styles.segmented} role="group" aria-label="数字人设置方式">
        <button type="button" aria-pressed={draft.mode === "same"} onClick={() => setDraft(current => switchMode(current, "same"))}>所有稿用同一个</button>
        <button type="button" aria-pressed={draft.mode === "each"} onClick={() => setDraft(current => switchMode(current, "each"))}>每条单独选</button>
      </div>}
      {draft.mode === "same" || draft.scripts.length <= 1 ? <div className={styles.sharedPick}>
        {presenterCell("all", draft.mode === "same" ? shared : assignmentFor(draft, draft.scripts[0]?.key ?? ""))}
        <p className={styles.muted}>{draft.scripts.length > 1 ? `一次设置，${draft.scripts.length} 条稿都用这个数字人。` : "选固定形象会同时带上它的声音。"}</p>
      </div> : <>{assignTable(false)}<button type="button" className={styles.quietButton} onClick={() => { const first = assignmentFor(draft, draft.scripts[0].key); setDraft(current => assign(current, "all", () => ({ ...first }))); }}>把第 1 条的设置用到全部</button></>}
      {props.libraryError && <p className={styles.warn}>{props.libraryError}<button type="button" className={styles.quietButton} onClick={props.onReloadLibrary}>重新读取</button></p>}
      <footer className={styles.stepFoot}><small /><button type="button" className={baseStyles.primaryButton} disabled={!stepDone(2)} onClick={() => goStep(textDrive ? 3 : 4)}>{textDrive ? "下一步：选音色" : "下一步：确认生成"}</button></footer>
    </div>}
  </section>;

  const stepThree = <section className={`${styles.step} ${draft.step === 3 ? styles.stepActive : ""} ${!textDrive ? styles.stepSkipped : ""}`} aria-label="第 3 步 音色">
    {stepHeader(3, draft.mode === "same" || draft.scripts.length <= 1 ? (voiceOf(shared.voiceId)?.name ?? "选择数字人的声音") : "每条稿的音色")}
    {draft.step === 3 && textDrive && <div className={styles.stepBody}>
      {draft.mode === "same" || draft.scripts.length <= 1 ? <div className={styles.sharedPick}>{voiceCell("all", draft.mode === "same" ? shared : assignmentFor(draft, draft.scripts[0]?.key ?? ""))}</div> : assignTable(true)}
      <div className={styles.actions}><button type="button" className={styles.quietButton} disabled aria-disabled="true" title="声音克隆暂未开通"><Plus size={14} />克隆新声音 · 暂未开通</button></div>
      <footer className={styles.stepFoot}><small /><button type="button" className={baseStyles.primaryButton} disabled={!stepDone(3)} onClick={() => goStep(4)}>下一步：确认生成</button></footer>
    </div>}
  </section>;

  const stepFour = <section className={`${styles.step} ${draft.step === 4 ? styles.stepActive : ""}`} aria-label="第 4 步 生成">
    {stepHeader(4, draft.scripts.length ? `共 ${totals.count} 条` : "确认后并行生成")}
    {draft.step === 4 && <div className={styles.stepBody}>
      <dl className={styles.summary}>
        <div><dt>条数</dt><dd>{totals.count} 条</dd></div>
        <div><dt>预计积分</dt><dd>{totals.credits === null ? "按实际用量" : `${totals.credits} 积分`}</dd></div>
        <div><dt>预计耗时</dt><dd>{totals.minutes[0]}–{totals.minutes[1]} 分钟</dd></div>
        <div><dt>数字人</dt><dd>{totals.presenters} 个</dd></div>
      </dl>
      <p className={styles.muted}>每条单独生成，同时最多 {PARALLEL_LIMIT} 条{totals.queued ? `，其余 ${totals.queued} 条排队` : ""}。某一条失败不影响其他条，失败的不扣积分，可以单独重试。{props.available !== undefined ? ` 当前可用 ${props.available.toLocaleString("zh-CN")} 积分。` : ""}</p>
      {draft.scripts.length > 1 && assignTable(textDrive)}
      {issues.length > 0 && <ul className={styles.issues}>{issues.map(issue => <li key={issue.text}><button type="button" onClick={() => goStep(issue.step)}>第 {issue.step} 步：{issue.text}</button></li>)}</ul>}
      {submitError && <p className={styles.warn} role="alert">{submitError}</p>}
      {short && <ShortOfCredits credits={totals.credits} />}
      <footer className={styles.stepFoot}><small /><button type="button" className={`${baseStyles.primaryButton} ${styles.generate}`} disabled={submitting || issues.length > 0 || short || uploading > 0} onClick={() => void generate()}>{submitting ? "正在提交…" : submitError && !short ? "再次确认（不会重复扣费）" : `确认生成 ${totals.count} 条${totals.credits ? ` · ${totals.credits} 积分` : ""}`}</button></footer>
    </div>}
  </section>;

  const boxes = batch ? resultBoxes(batch, stage => generationProgress({ status: "running", stage, kind: "lipsync" }).title) : [];
  const doneCount = boxes.filter(box => box.state === "done").length;
  const results = batch && <section ref={resultsRef} className={styles.results} aria-label="生成结果">
    <header className={styles.resultsHead}>
      <div><h2>生成结果</h2><p>{batchSettled(batch) ? `${doneCount} 条完成${boxes.length - doneCount ? `，${boxes.length - doneCount} 条失败` : ""}` : `共 ${boxes.length} 条 · 已完成 ${doneCount} 条 · 关掉页面也会继续生成`}</p></div>
      <div className={styles.resultsActions}>
        <button type="button" className={baseStyles.outlineButton} onClick={startOver}>再做一批</button>
        <button type="button" className={baseStyles.primaryButton} disabled={!doneCount} onClick={() => router.push(editingHref(batch.batch.id))}>去剪辑这 {doneCount || boxes.length} 条</button>
      </div>
    </header>
    <ol className={`${styles.resultGrid} ${boxes.length === 1 ? styles.resultSingle : ""}`}>{boxes.map((box, index) => {
      const item = batch.batch.items[index];
      const cover = avatarOf(item?.avatar_id ?? undefined)?.cover_url;
      return <li key={box.id} className={styles.resultBox} data-state={box.state}>
        <div className={styles.resultMedia}>
          {box.state === "done" && box.videoUrl ? <video controls playsInline preload="metadata" poster={cover ? mediaUrl(cover) : undefined} src={mediaUrl(box.videoUrl)} aria-label={`${box.title} 口播视频`} /> : <>{cover && <img src={mediaUrl(cover)} alt="" aria-hidden="true" />}<span className={styles.resultStatus}>{box.state === "failed" ? <X size={16} /> : null}{box.label}</span>{box.state === "running" && <span className={styles.progressLine} aria-hidden="true" />}</>}
        </div>
        <div className={styles.resultMeta}>
          <b><span>{index + 1}</span>{box.title}</b>
          {box.state === "failed" && box.error && <small className={styles.failText}>{box.error}</small>}
          <div>
            {box.state === "done" && box.videoUrl && <a className={styles.quietButton} href={mediaUrl(box.videoUrl)} download><Download size={14} />下载</a>}
            {box.state === "failed" && box.canRetry && <button type="button" className={styles.quietButton} disabled={retrying.includes(box.id)} onClick={() => void retry(box.id)}><RotateCcw size={14} />{retrying.includes(box.id) ? "正在重试" : "重试这一条"}</button>}
          </div>
        </div>
      </li>;
    })}</ol>
  </section>;

  const pickerTarget = picker?.target ?? "all";
  const pickerRow = pickerTarget === "all" ? (draft.mode === "same" ? shared : assignmentFor(draft, draft.scripts[0]?.key ?? "")) : assignmentFor(draft, pickerTarget);
  const pickerTitle = pickerTarget === "all" || draft.mode === "same" ? "选择数字人" : `第 ${draft.scripts.findIndex(s => s.key === pickerTarget) + 1} 条的数字人`;

  return <main className={styles.page}>
    <div className={styles.inner}>
      {props.stepBar}
      <header className={styles.pageHead}>
        <Link href="/video-studio" className={styles.back} aria-label="返回视频空间" onClick={event => { event.preventDefault(); props.onBack(); }}><ArrowLeft size={18} /></Link>
        <div><h1>口播</h1><p>选好文案、数字人和音色，一次生成多条口播视频。</p></div>
      </header>
      {!restored ? <div className={styles.loading} role="status">正在载入…</div> : <div className={styles.steps}>{stepOne}{stepTwo}{stepThree}{stepFour}</div>}
      {results}
    </div>
    {libraryOpen && <ScriptLibraryDialog api={api} chosen={new Set(draft.scripts.map(s => s.documentId).filter((id): id is string => !!id))} room={MAX_SCRIPTS - draft.scripts.length} onClose={() => setLibraryOpen(false)} onAdd={entries => { setDraft(current => addScripts(current.drive === "audio" ? switchDrive(current, "text") : current, entries.map(scriptFromLibrary))); setLibraryOpen(false); }} />}
    {picker?.kind === "presenter" && <PresenterPicker title={pickerTitle} personas={personas} avatars={avatars} voices={voices} selected={pickerRow}
      onClose={() => setPicker(null)}
      onApply={choice => { applyPresenter(pickerTarget, current => choice.kind === "persona" ? withPersona(choice.persona) : withAvatar(current, choice.avatar.id)); setPicker(null); }}
      onCreatePersona={() => gotoLibrary("/video-studio/avatars")} onCreateAvatar={() => gotoLibrary("/video-studio/avatars")} />}
    {picker?.kind === "voice" && <VoicePickerFor voices={usableVoices} row={pickerRow} playing={playing} onPreview={previewVoice} onClose={() => setPicker(null)} onApply={voiceId => { applyPresenter(pickerTarget, current => withVoice(current, voiceId)); setPicker(null); }} notify={notify} />}
  </main>;
}

function VoicePickerFor({ voices, row, playing, onPreview, onApply, onClose, notify }: { voices: VideoVoice[]; row: Assignment; playing: string; onPreview: (voice: VideoVoice) => void; onApply: (voiceId: string) => void; onClose: () => void; notify: Props["notify"] }) {
  const [selected, setSelected] = useState(row.voiceId ?? "");
  return <VoicePicker voices={voices} selectedId={selected} playingId={playing} onSelect={voice => setSelected(voice.id)} onPreview={onPreview} onApply={() => { if (selected) onApply(selected); }} onClose={onClose} onClone={() => notify("声音克隆暂未开通")} cloneLabel="克隆新声音 · 暂未开通" />;
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
