"use client";

import Link from "next/link";
import { ApiError } from "@/lib/api/api-error";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine, ArrowLeft, ArrowRight, AudioLines, BookOpenText, Check,
  ChevronDown, CircleHelp, Clapperboard, ExternalLink, Flame,
  FolderOpen, Play, Plus, Search,
  Settings2, Sparkles, Upload, UserRound, UsersRound, Video, Volume2,
} from "lucide-react";
import styles from "./video-studio.module.css";
import { Brand, Dialog, Empty } from "./studio-primitives";
import { VoiceBrowser, VoicePicker } from "./voice-picker";
import { AvatarPicker } from "./avatar-picker";
import { AvatarCloneDialog } from "./avatar-cloning";
import { GenerationPreview } from "./generation-preview";
import { StudioEditingScreen } from "./studio-editing-screen";
import { GuidedEmpty, PageHero, PortraitOutline } from "./page-hero";
import { ProjectStepBar } from "./project-step-bar";
import { TaskCenter } from "./task-center";
import { WritingStudio } from "./writing-studio";
import { EditingWorks } from "./editing-works";
import { GenerationConfirmation } from "./generation-confirmation";
import { ScriptProofread } from "./script-proofread";
import { Disclosure, MetadataGrid, Notice, TextDocument } from "./studio-content";
import { GenerationWorkCard } from "./generation-work-card";
import { StudioIntro } from "./studio-intro";
import { ScriptAssistantPanel } from "./script-assistant-panel";
import { ScriptHistory } from "./script-history";
import { ScriptLibrary } from "./script-library";
import { ScriptLibraryPage } from "./script-library-page";
import { voiceHref } from "@/features/video-studio/flow-params";
import { StudioToast, type ToastMessage, type ToastTone } from "./studio-toast";
import { useAutoReveal } from "@/features/video-studio/use-auto-reveal";
import { billableLabel, useVideoCredits } from "@/features/video-studio/credits";
import { CostLine, ShortOfCredits } from "./studio-content";
import { PENDING_COPY, decodePending, encodePending, pendingOutcome } from "@/features/video-studio/pending-submission";
import workflowStyles from "./studio-workflow.module.css";
import { MyVoices, VoiceCloneDialog } from "./voice-cloning";
import { useVoiceClones } from "@/features/video-studio/voice-clones";
import type { AssistantMode } from "@/features/video-studio/assistance";
import { useScriptReference } from "@/features/video-studio/use-script-reference";
import { useProjectSession } from "@/features/video-studio/use-project-session";
import { useVideoLibrary, type VideoAvatar, type GenerationJob } from "@/features/video-studio/library";
import type { VideoDraft, VideoContent, VideoVersion } from "@/features/video-studio/projects";
import { mediaUrl } from "@/lib/api/base-url";

export type StudioScreen = "home" | "writing" | "create" | "avatars" | "voices" | "library" | "works" | "editing";
type Avatar = VideoAvatar;
type Draft = VideoDraft;
type SavedCopy = { id: string; title: string; text: string; date: string };
type DemoWork = { id: string; draft: Draft; date: string; projectId: string; content: VideoContent };
type Modal = "avatar" | "voice" | "avatar-clone" | "voice-clone" | "generate" | "preview" | "help" | "history" | "avatar-preview" | "h3-template" | "real-preview" | "proofread" | null;

const EMPTY_DRAFT: Draft = { name: "未命名视频", text: "", avatarId: "", voiceId: "", speed: 1, emotion: "自然", language: "auto", quality: "1080P", drive: "text" };
const imageOf = (avatar: Avatar | undefined) => avatar?.cover_url || undefined;
const EMPTY_AVATAR: Avatar = { id: "", name: "请选择数字人", tag: "", gender: "未知", source: "quanyu_public", cover_url: "", ready: false };
const hrefOf = (screen: StudioScreen) => screen === "home" ? "/video-studio" : `/video-studio/${screen}`;
const dateLabel = (date: string) => Number.isNaN(new Date(date).getTime()) ? "" : new Date(date).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
const uid = () => crypto.randomUUID();

export function VideoStudio({ screen, userId, workspaceId }: { screen: StudioScreen; userId: string; workspaceId: string }) {
  const router = useRouter();
  const library = useVideoLibrary(workspaceId);
  const clones = useVoiceClones(workspaceId);
  const credits = useVideoCredits(workspaceId);
  const AVATARS = library.avatars;
  const VOICES = library.voices;
  const [templateAvatar, setTemplateAvatar] = useState<Avatar>();
  const [avatarPreview, setAvatarPreview] = useState<Avatar>();
  const [selectedPreview, setRealPreview] = useState<GenerationJob>();
  const realPreview = library.jobs.find(job => job.id === selectedPreview?.id) || selectedPreview;
  const [submitting, setSubmitting] = useState(false);
  const [generationError, setGenerationError] = useState("");
  const generationRequest = useRef<Parameters<typeof library.submit>[0] | undefined>(undefined);
  const pendingKey = `polaris-video-generation:${userId}:${workspaceId}`;
  const pendingSavedAt = useRef(0);
  const isSubmission = (value: unknown): value is Parameters<typeof library.submit>[0] => {
    const body = value as Parameters<typeof library.submit>[0] | null;
    return !!body && typeof body === "object" && ["lipsync", "h3_template"].includes(body.kind) && typeof body.request_id === "string" && typeof body.avatar_id === "string";
  };
  const restorePending = () => {
    if (generationRequest.current) return;
    try {
      const pending = decodePending(sessionStorage.getItem(pendingKey), isSubmission);
      if (pending) { generationRequest.current = pending.body; pendingSavedAt.current = pending.savedAt; }
    } catch { /* In-memory retry still works if storage is unavailable. */ }
  };
  const clearPending = () => { generationRequest.current = undefined; pendingSavedAt.current = 0; setGenerationError(""); try { sessionStorage.removeItem(pendingKey); } catch {} };
  const persistPending = () => {
    if (!generationRequest.current) return;
    pendingSavedAt.current ||= Date.now();
    try { sessionStorage.setItem(pendingKey, encodePending(generationRequest.current, pendingSavedAt.current)); } catch {}
  };
  // 提交结果不确定时由页面自动按请求号核对：查到就显示原任务，确认没到达才允许重新提交；从不自动重发付费请求。
  const reconcileTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const reconcilePending = async () => {
    restorePending();
    const pending = generationRequest.current;
    if (!pending) return;
    clearTimeout(reconcileTimer.current);
    setGenerationError(PENDING_COPY.checking);
    let lookup: { received: boolean; job: GenerationJob | null };
    try { lookup = await library.lookupRequest(pending.request_id); }
    catch { reconcileTimer.current = setTimeout(() => void reconcilePending(), 10000); return; }
    if (generationRequest.current?.request_id !== pending.request_id) return;
    const outcome = pendingOutcome(lookup, pendingSavedAt.current);
    if (outcome === "found" && lookup.job) {
      clearPending(); notify(PENDING_COPY.found, "success");
      if (pending.kind === "lipsync") { setRealPreview(lookup.job); setModal("real-preview"); }
      void library.reload();
    } else if (outcome === "absent") {
      clearPending(); notify(PENDING_COPY.absent);
    } else {
      reconcileTimer.current = setTimeout(() => void reconcilePending(), 10000);
    }
  };
  const submissionError = (error: unknown) => {
    if (error instanceof ApiError && error.status && error.status >= 400 && error.status < 500) { clearPending(); notify(error.message); }
    else { setGenerationError(PENDING_COPY.checking); void reconcilePending(); }
  };
  const persisted = useProjectSession(userId, workspaceId);
  const { session, content, projectId, status } = persisted;
  const saveEditingProject = async () => {
    if (!session.state.content.draft.name.trim() || session.state.content.draft.name === "未命名视频") {
      session.edit({ ...session.state.content, draft: { ...session.state.content.draft, name: "口播剪辑 · " + new Date().toLocaleDateString("zh-CN") } });
    }
    await session.save();
  };
  const draft = content.draft;
  const setDraft = (value: Draft | ((current: Draft) => Draft)) => session.edit({ ...session.state.content, draft: typeof value === "function" ? value(session.state.content.draft) : value });
  const copies: SavedCopy[] = persisted.copies.map(v => ({ id: v.id, title: v.snapshot.draft.name === "未命名视频" ? v.snapshot.draft.text.slice(0, 18) : v.snapshot.draft.name, text: v.snapshot.draft.text, date: v.created_at }));
  const works: DemoWork[] = persisted.tasks.map(t => ({ id: t.id, draft: t.snapshot.draft, date: t.created_at, projectId: t.project_id, content: t.snapshot }));
  const loaded = status !== "loading";
  const [modal, setModal] = useState<Modal>(null);
  const [toast, setToast] = useState<ToastMessage>();
  const dismissToast = useCallback(() => setToast(undefined), []);
  const [search, setSearch] = useState("");
  const [playingVoice, setPlayingVoice] = useState("");
  const voicePlayer = useRef<HTMLAudioElement | null>(null);
  const [gender, setGender] = useState("全部");
  const [assetTab, setAssetTab] = useState("public");
  const [selectedAvatar, setSelectedAvatar] = useState(EMPTY_DRAFT.avatarId);
  const [selectedVoice, setSelectedVoice] = useState("");
  const [rightTab, setRightTab] = useState("assistant");
  const assistantPanelRef = useRef<HTMLElement>(null);
  const scriptInputRef = useRef<HTMLTextAreaElement>(null);
  const revealScript = () => requestAnimationFrame(() => {
    scriptInputRef.current?.focus({ preventScroll: true });
    if (window.matchMedia("(max-width: 1050px)").matches) scriptInputRef.current?.scrollIntoView({ block: "center", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  });
  const [previewWork, setPreviewWork] = useState<DemoWork>();
  const [audioSelection, setAudio] = useState<{ projectId: string; name: string; url: string }>();
  const audio = audioSelection?.projectId === projectId ? audioSelection : undefined;
  const audioUrl = useRef<string | undefined>(undefined);
  const [speaking, setSpeaking] = useState(false);
  const avatar = AVATARS.find(item => item.id === draft.avatarId) ?? EMPTY_AVATAR;
  const voice = VOICES.find(item => item.id === draft.voiceId);
  const rawReference = content.references.find(r => r.note.includes("语音转写")) || content.references.find(r => r.original_text);
  const notify = useCallback((text: string, tone: ToastTone = "info") => setToast({ id: Date.now(), text, tone }), []);
  const updateDraft = (patch: Partial<Draft>) => setDraft(current => ({ ...current, ...patch }));
  const applyVoice = (voiceId: string) => updateDraft({ voiceId, emotion: "自然", language: "auto" });
  const previewVoice = (item: typeof VOICES[number]) => {
    voicePlayer.current?.pause();
    if (playingVoice === item.id) { setPlayingVoice(""); return; }
    if (!item.preview_url) { setPlayingVoice(""); notify("此音色试听正在准备，稍后再试"); return; }
    const player = new Audio(item.preview_url);
    voicePlayer.current = player;
    player.onended = () => setPlayingVoice("");
    player.onerror = () => { setPlayingVoice(""); notify("试听暂不可用，请稍后重试"); };
    setPlayingVoice(item.id);
    void player.play().catch(() => { setPlayingVoice(""); notify("试听暂不可用，请稍后重试"); });
  };

  useEffect(() => () => { if (audioUrl.current) URL.revokeObjectURL(audioUrl.current); window.speechSynthesis?.cancel(); }, []);
  useEffect(() => () => { voicePlayer.current?.pause(); }, []);
  // 页面打开时，若有上次没确认结果的提交，自动核对一次。
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void reconcilePending(); return () => clearTimeout(reconcileTimer.current); }, []);
  useEffect(() => { voicePlayer.current?.pause(); void Promise.resolve().then(() => setPlayingVoice("")); }, [modal, screen]);

  const attempt = (operation: () => Promise<unknown>) => { void operation().catch(error => notify(error instanceof Error ? error.message : "操作未完成，请重试", "error")); };
  const writing = useScriptReference({ userId, workspaceId, projectId, session, notify, attempt, updateDraft, onAdopted: () => { setModal(null); revealScript(); } });
  const go = (next: StudioScreen) => attempt(async () => { await session.save(); router.push(hrefOf(next) + (session.state.revision ? `?project=${session.state.projectId}` : "")); });
  /** 文案库/爆款文案 → 口播页，带上选中的文案（?scripts=id1,id2，W2 读取）。 */
  const openVoiceWith = (ids: string[]) => attempt(async () => { await session.save(); router.push(voiceHref(ids, session.state.revision ? session.state.projectId : undefined)); });
  const continueWithAvatar = (job: GenerationJob) => {
    if (job.kind !== "h3_template" || job.status !== "completed") return;
    updateDraft({ avatarId: job.avatar_id });
    setModal(null); go("create"); revealScript();
  };
  const editGeneratedVideo = (job: GenerationJob) => attempt(async () => {
    if (job.kind !== "lipsync" || job.status !== "completed" || !job.project_id) return;
    await session.save();
    if (session.state.projectId !== job.project_id) await session.select(job.project_id);
    setModal(null);
    router.push(`/video-studio/editing?project=${encodeURIComponent(job.project_id)}&generation=${encodeURIComponent(job.id)}`);
  });
  const open =(next: Modal) => {
    restorePending();
    if (next === "generate" && generationRequest.current?.kind === "h3_template") { setTemplateAvatar(AVATARS.find(a => a.id === generationRequest.current?.avatar_id)); next = "h3-template"; }
    setGenerationError(generationRequest.current ? PENDING_COPY.checking : "");
    if (generationRequest.current) void reconcilePending();
    setSearch(""); setGender("全部"); if (next !== "voice-clone") setAssetTab("public");
    setSelectedAvatar(AVATARS.some(a => a.id === draft.avatarId) ? draft.avatarId : AVATARS[0]?.id || ""); setSelectedVoice(draft.voiceId);
    if (next === "generate" && !generationRequest.current) setGenerationError("");
    setModal(next);
  };
  const selectAvatar = (item: Avatar) => { updateDraft({ avatarId: item.id }); go("create"); };
  const filteredAvatars = AVATARS.filter(item => (assetTab === "own" ? item.source === "self_owned" : item.source === "quanyu_public") && (gender === "全部" || item.gender === gender) && `${item.name}${item.tag}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const [visibleAvatarCount, hasMoreAvatars, avatarLoadMoreRef] = useAutoReveal(filteredAvatars.length, `${screen}:${assetTab}:${gender}:${search}`);
  const avatarLabel = (item: Avatar) => item.name.replace(/-(sit_body|whole_body)$/, "").replaceAll("-", " · ");
  const showAssistant = (mode: AssistantMode, reveal = true) => {
    writing.setAssistantMode(mode); setRightTab("assistant");
    if (reveal && window.matchMedia("(max-width: 1050px)").matches) requestAnimationFrame(() => assistantPanelRef.current?.scrollIntoView({ block: "start", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }));
  };
  const copyText = (text: string) => attempt(async () => { await navigator.clipboard.writeText(text); notify("全文已复制", "success"); });

  const audition = (text = draft.text || "你好，欢迎来到极光商绘，让每一个好产品，都有自己的表达。") => {
    if (!("speechSynthesis" in window)) { notify("当前浏览器不支持本地试听，请使用音频驱动体验"); return; }
    if (speaking) { window.speechSynthesis.cancel(); setSpeaking(false); return; }
    const utterance = new SpeechSynthesisUtterance(text.slice(0, 600));
    utterance.lang = "zh-CN"; utterance.rate = draft.speed;
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => { setSpeaking(false); notify("浏览器试听暂不可用，确认生成仍使用所选正式音色"); };
    setSpeaking(true); window.speechSynthesis.speak(utterance);
    notify("正在使用浏览器声音检查文案；确认生成使用所选正式音色");
  };
  const saveCopy = () => {
    if (!draft.text.trim()) return notify("请先输入文案");
    if (copies.some(copy => copy.text === draft.text)) return notify("这段文案已经在文案库中");
    attempt(async () => { await session.save("library"); notify("已存入文案库，可在右侧文案库中查看", "success"); });
  };
  const generate = () => {
    if (!AVATARS.some(a => a.id === draft.avatarId)) { notify("请选择真实数字人形象"); return open("avatar"); }
    if (!avatar.ready) { setTemplateAvatar(avatar); return open("h3-template"); }
    if (draft.drive === "text" && !draft.text.trim()) return notify("请输入视频文案");
    if (draft.drive === "text" && !voice) return open("voice");
    if (draft.drive === "text" && voice?.available === false) return notify("所选音色暂未启用，请选择可用音色");
    if (draft.drive === "audio" && !draft.audioAssetId) return notify("请先上传一段音频");
    open("generate");
  };
  const createRealVideo = () => attempt(async () => {
    if (submitting) return;
    restorePending();
    if (generationRequest.current && generationRequest.current.kind !== "lipsync") { notify("请先查询上一条动作模板提交"); return; }
    setSubmitting(true);
    try {
      await session.save();
      generationRequest.current ??= { request_id: uid(), kind: "lipsync", avatar_id: avatar.id, project_id: session.state.projectId, expected_revision: session.state.revision, audio_id: draft.audioAssetId || undefined };
      persistPending();
      const job = await library.submit(generationRequest.current);
      clearPending();
      setRealPreview(job); setModal("real-preview"); setRightTab("works");
    } catch (error) { submissionError(error); } finally { setSubmitting(false); }
  });
  const createTemplate = () => attempt(async () => {
    if (!templateAvatar || submitting) return;
    restorePending();
    if (generationRequest.current && generationRequest.current.kind !== "h3_template") { notify("请先查询上一条视频提交"); return; }
    setSubmitting(true);
    try {
      generationRequest.current ??= { request_id: uid(), kind: "h3_template", avatar_id: templateAvatar.id };
      persistPending();
      await library.submit(generationRequest.current);
      clearPending(); setModal(null); notify("原创动作模板已提交，完成后请先预览确认入库");
    } catch (error) { submissionError(error); } finally { setSubmitting(false); }
  });

  const tabs = (items: { key: string; label: string }[], value: string, onChange: (key: string) => void) => <div className={styles.tabs}>{items.map(item => <button type="button" key={item.key} className={value === item.key ? styles.activeTab : ""} aria-pressed={value === item.key} onClick={() => onChange(item.key)}>{item.label}</button>)}</div>;
  const filters = (placeholder: string) => <div className={styles.filterRow}><div className={styles.pills}>{["全部", "男", "女"].map(item => <button type="button" key={item} aria-pressed={gender === item} className={gender === item ? styles.activePill : ""} onClick={() => setGender(item)}>{item === "全部" ? item : `${item}性`}</button>)}</div><label className={styles.search}><Search size={15} /><input aria-label={placeholder} placeholder={placeholder} value={search} onChange={event => setSearch(event.target.value)} /></label></div>;
  const avatarGrid = (inDialog = false) => <><div className={`${styles.avatarGrid} ${inDialog ? styles.modalGrid : ""}`}>{filteredAvatars.slice(0, visibleAvatarCount).map(item => <div key={item.id} className={`${styles.avatarCard} ${inDialog && selectedAvatar === item.id ? styles.selectedCard : ""}`}>
    <button type="button" className={styles.avatarImage} aria-label={`预览${item.name}`} onClick={() => { setAvatarPreview(item); setModal("avatar-preview"); }}><img src={mediaUrl(imageOf(item))} alt={`${item.name}数字人形象`} loading="lazy" /><span className={styles.avatarTag}>{item.tag}</span><span className={styles.cardHover}><Play size={15} fill="currentColor" />预览形象</span></button>
    <div className={styles.avatarCaption}><strong>{avatarLabel(item)}</strong><span>{item.gender === "未知" ? item.tag : item.gender}</span><button type="button" className={styles.textButton} onClick={() => inDialog ? setSelectedAvatar(item.id) : selectAvatar(item)}>{inDialog ? (selectedAvatar === item.id ? "已选择" : "选择") : "使用"}</button>{item.source === "self_owned" && !item.ready && <button type="button" className={styles.textButton} onClick={() => { setTemplateAvatar(item); open("h3-template"); }}>生成动作模板</button>}</div>
  </div>)}</div>{filteredAvatars.length > 0 && <div ref={avatarLoadMoreRef} className={workflowStyles.galleryProgress} role="status">{hasMoreAvatars ? `已展示 ${visibleAvatarCount} / ${filteredAvatars.length}，向下浏览自动加载` : `已展示全部 ${filteredAvatars.length} 个形象`}</div>}</>;
  const voiceGrid = () => <VoiceBrowser voices={VOICES.filter(item => item.source !== "own" && item.available !== false)} selectedId={selectedVoice || draft.voiceId} playingId={playingVoice} onPreview={previewVoice} onSelect={item => { setSelectedVoice(item.id); applyVoice(item.id); go("create"); }} />;
  const copyList = (compact = false) => <ScriptLibrary copies={copies} compact={compact} keyword={search} onCopy={copyText} onCreate={() => go("create")} onUse={copy => { updateDraft({ text:copy.text, name:copy.title }); if (!compact) go("create"); notify("文案已填入编辑器"); }} />;
  const demoWorkList = (compact = false) => works.length ? <div className={`${styles.worksGrid} ${compact ? styles.compactWorks : ""}`}>{works.filter(work => work.draft.name.includes(compact ? "" : search)).map(work => {
    const model = AVATARS.find(item => item.id === work.draft.avatarId) ?? EMPTY_AVATAR;
    return <article className={styles.workCard} key={work.id}><button type="button" className={styles.workImage} onClick={() => { setPreviewWork(work); setModal("preview"); }}><img src={mediaUrl(imageOf(model))} alt={model.name} /><span>本地演示</span><i><Play size={21} fill="currentColor" /></i></button><div><b>{work.draft.name}</b><time>{dateLabel(work.date)}</time><p>演示预览 · 尚未生成视频</p><button className={styles.textButton} onClick={() => attempt(async () => { await session.select(work.projectId); session.edit(work.content); await session.save(); go("create"); if (compact) setRightTab("assistant"); })}>继续编辑 <ArrowRight size={14} /></button></div></article>;
  })}</div> : (compact ? <Empty icon={<Clapperboard size={29} />} title="你的作品将在这里出现" description="选择形象，写下文案，开始制作第一个视频。" /> : <GuidedEmpty title="还没有口播作品" description="三步做出第一条数字人口播，生成后会出现在这里。" steps={["写一篇文案，或从爆款文案定稿", "选一个形象和声音", "确认生成，完成后可直接送去剪辑"]} action={<button className={styles.primaryButton} onClick={() => go("writing")}>从写文案开始 <Plus size={16} /></button>} motif="works" />);


  const workList = (compact = false) => {
    const matchingJobs = library.jobs.filter(job => compact || `${job.snapshot?.draft.name || ""} ${AVATARS.find(avatar => avatar.id === job.avatar_id)?.name || ""}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
    return <><div className={`${styles.worksGrid} ${compact ? styles.compactGenerationWorks : ""}`}>{matchingJobs.map(job => <GenerationWorkCard key={job.id} job={job} avatar={AVATARS.find(a => a.id === job.avatar_id) || EMPTY_AVATAR} onPreview={() => { setRealPreview(job); setModal("real-preview"); }} onResume={() => attempt(() => library.resume(job.id))} resuming={library.resumingIds.includes(job.id)} />)}</div>{!matchingJobs.length && !!library.jobs.length && !works.length && <Empty icon={<Search size={25} />} title="没有找到匹配作品" description="换一个视频名称或形象关键词试试。" />}{works.length > 0 ? demoWorkList(compact) : !library.jobs.length && demoWorkList(compact)}<button type="button" className={styles.textButton} onClick={() => attempt(() => library.reload())}>刷新任务</button></>;
  };

  const worksContent = <>
    <PageHero eyebrow="我的作品" title="每一个好想法，" accent="都留下作品" description="进行中的任务、剪辑成片和数字人口播都在这里，随时回到原任务继续。" facts={[{ label: "口播任务", value: library.jobs.length }, { label: "项目", value: persisted.projects.length }]} actions={<button className={styles.primaryButton} onClick={() => go("create")}><Plus size={16} />创作视频</button>} motif="works" />
    <div className={styles.listHeading}><b>全部作品</b><label className={styles.search}><Search size={15} /><input aria-label="搜索作品" placeholder="搜索作品" value={search} onChange={event => setSearch(event.target.value)} /></label></div>
    <EditingWorks userId={userId} workspaceId={workspaceId} keyword={search} />
    <section aria-label="生成作品">
      <div className={styles.sectionHeading}><h2>生成作品</h2><span>{library.jobs.length + works.length} 项</span></div>
      {workList()}
    </section>
  </>;

  const assistant = <ScriptAssistantPanel workspaceId={workspaceId} projectId={projectId} session={session} content={content} writing={writing}
    onRevealScript={revealScript} notify={notify} attempt={attempt} copyText={copyText} updateDraft={updateDraft} onGoWriting={() => go("writing")} />;

  const stepBar = (step: "writing" | "create" | "editing") => <ProjectStepBar workspaceId={workspaceId} projectId={projectId} saved={Boolean(persisted.revision)} screen={step} hasScript={Boolean(draft.text.trim())} jobs={library.jobs} onGo={go} />;
  const editor = <main className={styles.editor}>
    <section className={styles.editorMain} aria-label="视频编辑器">{stepBar("create")}<header className={styles.editorHeader}><Link href={persisted.revision ? `/video-studio?project=${projectId}` : "/video-studio"} onClick={event => { event.preventDefault(); go("home"); }} className={styles.back} aria-label="返回视频空间"><ArrowLeft size={19} /></Link>{tabs([{ key: "text", label: "文本驱动" }, { key: "audio", label: "音频驱动" }], draft.drive, drive => updateDraft({ drive: drive as Draft["drive"] }))}<label className={styles.projectName}><span>视频名称</span><input aria-label="视频名称" value={draft.name} maxLength={80} onChange={event => updateDraft({ name: event.target.value })} /></label><select aria-label="切换视频项目" value={persisted.projects.some(p => p.id === projectId) ? projectId : ""} onChange={event => attempt(() => session.select(event.target.value))}><option value="" disabled>新项目</option>{persisted.projects.map(p => <option value={p.id} key={p.id}>{p.content.draft.name || "未命名视频"}</option>)}</select><button type="button" className={styles.textButton} onClick={() => attempt(() => session.newProject())}>新建</button><span role="status" aria-label="项目保存状态" className={styles.autosave}><Check size={12} />{!loaded ? "载入中" : status === "saved" ? "已保存" : status === "saving" ? "保存中" : status === "dirty" ? "待保存" : "未保存"}</span></header>
      <div className={styles.editorBody}><div className={styles.portraitColumn}><div className={styles.portrait}>{avatar.id ? <><img src={mediaUrl(imageOf(avatar))} alt={avatarLabel(avatar)} /><span className={styles.portraitBadge}>{avatarLabel(avatar)} · {avatar.tag}</span><span className={styles.portraitRatio}>9:16</span></> : <div className={styles.portraitEmpty}><PortraitOutline /><b>先选择出镜形象</b><span>公共模特，随时开始创作</span></div>}</div><button type="button" className={styles.selectAvatar} onClick={() => open("avatar")}><UsersRound size={17} />选择数字人<ChevronDown size={15} /></button><div className={styles.portraitNote}><Video size={13} /> 数字人口播视频</div></div>
        <div className={styles.scriptColumn}>{draft.drive === "text" ? <><button type="button" className={styles.voiceSelector} onClick={() => open("voice")}><span className={styles.voiceSelectorIcon}><AudioLines size={23} /></span><span><b>{voice?.name ?? "请选择声音"}</b><small>{voice ? `${voice.gender === "未知" ? "" : `${voice.gender}声 · `}${voice.tag}` : "让你的数字人拥有专属声音"}</small></span><ChevronDown size={16} /></button><div className={styles.voiceParams}><label className={styles.speed}><span>语速 <b>{draft.speed.toFixed(1)}×</b></span><input aria-label="语速" type="range" min="0.5" max="1.5" step="0.1" value={draft.speed} onChange={event => updateDraft({ speed: Number(event.target.value) })} /></label><label><span>情绪</span><select aria-label="情绪" value={draft.emotion} disabled={!voice || (voice.emotions?.length ?? 1) < 2} onChange={event => updateDraft({ emotion: event.target.value as Draft["emotion"] })}>{(voice?.emotions?.includes(draft.emotion) ? voice.emotions : [draft.emotion, ...(voice?.emotions || []).filter(e => e !== draft.emotion)]).map(emotion => <option key={emotion}>{emotion}</option>)}</select></label><label><span>语言</span><select aria-label="语言" value={draft.language || "auto"} disabled={!voice || Object.keys(voice.languages || {}).length < 2} onChange={event => updateDraft({ language: event.target.value })}>{Object.entries(voice?.languages || { auto: "自动识别文案语言" }).map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></label></div>
          <div className={styles.scriptBox}><div className={styles.scriptToolbar}><span>视频文案</span><button type="button" onClick={() => setModal("proofread")}>原文校对</button><button type="button" title="播放所选音色的固定短样片" onClick={() => voice ? previewVoice(voice) : open("voice")}><Volume2 size={15} />{playingVoice && playingVoice === voice?.id ? "停止试听" : "音色试听"}</button></div><textarea ref={scriptInputRef} aria-label="视频文案" value={draft.text} placeholder={"请输入你希望数字人讲述的内容…\n\n也可以用右侧文案助手原创，或去「爆款文案」照着爆款仿写。"} maxLength={3000} onChange={event => updateDraft({ text: event.target.value })} /><span className={styles.wordCount}>{draft.text.length} / 3000</span></div><div className={styles.copyActions}><button type="button" onClick={() => go("writing")}><Flame size={15} />照着爆款写</button><button type="button" onClick={() => showAssistant("create")}><Sparkles size={15} />AI 文案创作</button><button type="button" onClick={() => attempt(async () => { await session.loadHistory(); setModal("history"); })}>文案版本</button><button type="button" onClick={saveCopy}><FolderOpen size={15} />存入文案库</button></div></> : <div className={styles.audioDrive}><span className={styles.bigIcon}><AudioLines size={37} /></span><h2>上传音频，驱动数字人</h2><p>使用已经录制好的声音，让数字人替你讲述。</p><label className={styles.uploadButton}><Upload size={16} />选择音频<input type="file" accept="audio/*" onChange={event => {
            const file = event.target.files?.[0]; if (!file) return;
            if (!file.type.startsWith("audio/")) { notify("请选择音频文件"); return; }
            if (file.size > 50 * 1024 * 1024) { notify("请选择 50 MB 以内的音频"); return; }
            if (audioUrl.current) URL.revokeObjectURL(audioUrl.current);
            const url = URL.createObjectURL(file); audioUrl.current = url; setAudio({ projectId, name: file.name, url }); updateDraft({ audioAssetId: null });
            const uploadProjectId = projectId;
            attempt(async () => { const uploaded = await library.uploadAudio(file); if (session.state.projectId === uploadProjectId) updateDraft({ audioAssetId: uploaded.id }); notify("音频已保存，可用于口型驱动"); });
            session.edit({ ...session.state.content, media: [{ id: uid(), kind: "audio", name: file.name, mime_type: file.type, size_bytes: file.size, availability: "local_only" }, ...session.state.content.media.filter(m => m.kind !== "audio")] });
          }} /></label>{draft.audioAssetId && !audio && <audio controls src={mediaUrl(`/api/v1/video-studio/workspaces/${workspaceId}/audio-files/${draft.audioAssetId}`)} />}{audio ? <div className={styles.audioFile}><b>{audio.name}</b><audio controls src={mediaUrl(audio.url)} /><small>上传完成后可跨设备继续使用</small></div> : <small>{draft.audioAssetId ? "音频已保存，可继续生成" : content.media.find(m => m.kind === "audio") ? `已关联 ${content.media.find(m => m.kind === "audio")?.name}，请重新选择原文件` : "支持 MP3、WAV、M4A · 最大 50 MB"}</small>}</div>}</div></div>
      <footer className={styles.editorFooter}><label><Settings2 size={15} /><select aria-label="视频清晰度" value="source" disabled title="按所选动作模板的原始分辨率交付"><option value="source">模板原始清晰度</option></select></label>{credits.note(["lipsync"]).insufficient && <ShortOfCredits credits={credits.note(["lipsync"]).credits} />}<button type="button" className={styles.generateButton} disabled={credits.note(["lipsync"]).insufficient} onClick={generate}><Video size={18} />{billableLabel("生成视频", credits.note(["lipsync"]).credits)}</button></footer>
    </section>
    <aside ref={assistantPanelRef} className={styles.editorAside}><div className={styles.rightTabs} role="group" aria-label="创作工具">{[{ key: "works", label: "作品" }, { key: "library", label: "文案库" }, { key: "assistant", label: "文案助手" }].map(item => <button type="button" key={item.key} className={rightTab === item.key ? styles.activeRightTab : ""} aria-pressed={rightTab === item.key} onClick={() => setRightTab(item.key)}>{item.label}</button>)}</div><div className={styles.rightContent}>{rightTab === "assistant" ? assistant : rightTab === "works" ? <div className={styles.workList}>{workList(true)}</div> : copyList(true)}</div></aside>
  </main>;

  const entries = [
    { key: "writing", title: "写爆款文案", note: "推荐", copy: "找对标、拆结构，按产品事实改写成自己的口播稿。", step: "从文案开始", action: () => go("writing") },
    { key: "create", title: "从文案做口播", copy: "已有文案，选好形象和声音，生成数字人口播。", step: "从口播开始", action: () => go("create") },
    { key: "editing", title: "已有视频直接剪辑", copy: "上传口播或选择已生成的视频，套用模板出片。", step: "从剪辑开始", action: () => go("editing") },
  ];
  const navGroups = [
    { label: "创作流程", items: [
      { key: "writing" as const, label: "爆款文案", icon: <Sparkles size={18} /> },
      { key: "create" as const, label: "创作视频", icon: <Video size={18} /> },
      { key: "editing" as const, label: "智能剪辑", icon: <Clapperboard size={18} /> },
      { key: "works" as const, label: "我的作品", icon: <ArrowDownToLine size={18} /> },
    ] },
    { label: "素材库", items: [
      { key: "avatars" as const, label: "形象", icon: <UserRound size={18} /> },
      { key: "voices" as const, label: "声音", icon: <AudioLines size={18} /> },
      { key: "library" as const, label: "文案库", icon: <BookOpenText size={18} /> },
    ] },
  ];
  const homeContent = <><StudioIntro avatarCount={AVATARS.filter(a => a.ready).length} voiceCount={VOICES.length} onCreate={() => go("create")} /><section className={styles.entryCards} aria-label="开始创作">{entries.map(entry => <button key={entry.key} type="button" className={`${styles.entryCard} ${entry.note ? styles.entryPrimary : ""}`} onClick={entry.action}><span className={styles.entryStep}>{entry.step}</span><h2>{entry.title}{entry.note && <small>{entry.note}</small>}</h2><p>{entry.copy}</p><span className={styles.entryGo}>开始 <ArrowRight size={14} /></span></button>)}</section><div className={styles.sectionHeading}><div><h2>素材库 · 公共数字人</h2><span>选一个形象，直接进入口播</span></div></div>{filters("搜索数字人")}{avatarGrid()}{!filteredAvatars.length && <Empty icon={<Search size={25} />} title="没有找到匹配的数字人" description="试试其他名字或筛选条件。" />}</>;
  const assetContent = <><PageHero eyebrow={screen === "avatars" ? "形象" : "声音"} title={screen === "avatars" ? "为每个故事，" : "一个熟悉的声音，"} accent={screen === "avatars" ? "选对讲述者" : "更有温度"} description={screen === "avatars" ? "公共模特随时可用；上传一张清晰照片或一段出镜视频，就能创建你的数字分身。" : "系统音色开箱即用；上传 10～20 秒本人录音，即可克隆专属声音。"} facts={screen === "avatars" ? [{ label: "可用形象", value: AVATARS.filter(a => a.ready).length }, { label: "我的定制", value: AVATARS.filter(a => a.source === "self_owned").length }] : [{ label: "系统音色", value: VOICES.filter(v => v.source !== "own").length }, { label: "我的声音", value: Math.max(clones.voices.length, VOICES.filter(v => v.source === "own").length) }]} actions={<button type="button" className={styles.primaryButton} onClick={() => open(screen === "avatars" ? "avatar-clone" : "voice-clone")}><Plus size={17} />{screen === "avatars" ? "克隆新形象" : "克隆新声音"}</button>} motif={screen === "avatars" ? "avatar" : "voice"} />{tabs([{ key: "own", label: screen === "avatars" ? "我的定制" : "我的声音" }, { key: "public", label: screen === "avatars" ? "公共模特" : "系统声音" }], assetTab, setAssetTab)}{assetTab === "own" && screen === "voices" ? <MyVoices clones={clones} onClone={() => open("voice-clone")} onApply={id => attempt(async () => { await library.reload(); applyVoice(id); await session.save(); router.push(hrefOf("create") + "?project=" + session.state.projectId); })} onReload={library.reload} onError={text => notify(text, "error")} /> : <>{screen === "avatars" && filters("搜索数字人")}{screen === "avatars" ? <>{avatarGrid()}{!filteredAvatars.length && (AVATARS.length ? <Empty icon={<Search size={25} />} title="没有找到匹配的数字人" description="试试其他名字或筛选条件。" /> : <GuidedEmpty title={library.error ? "形象库暂时读不到" : "还没有可用的形象"} description={library.error ? "数字人服务暂时没有响应，已保存的口播和剪辑不受影响。稍后重新读取即可。" : "公共模特会显示在这里；也可以用一张清晰照片克隆你自己的数字分身。"} steps={["上传一张正面清晰照片或一段出镜视频", "预览生成的动作，确认满意", "加入形象库，写文案时直接选用"]} action={library.error ? <button type="button" className={styles.outlineButton} onClick={() => attempt(() => library.reload())}>重新读取</button> : <button type="button" className={styles.primaryButton} onClick={() => open("avatar-clone")}><Plus size={16} />克隆新形象</button>} motif="avatar" />)}</> : <><p className={styles.inlineNote}>选择适合视频风格的声音，点击试听预览</p>{voiceGrid()}</>}</>}</>;

  const blocked = status === "loading" || Boolean(persisted.recovery) || (!projectId && Boolean(persisted.error));
  const restoreVersion = (version: VideoVersion) => attempt(async () => {
    await session.restoreVersion(version);
    setModal(null);
    notify("历史版本已恢复为当前草稿，原版本保留", "success");
  });
  return <div className={`${styles.studio} ${screen === "editing" ? styles.editingStudio : ""}`}>
    {(persisted.error || persisted.recovery) && <div role="alert" className={styles.persistenceNotice}><span>{persisted.recovery ? "发现本机未保存内容，请选择恢复或使用服务端版本。" : persisted.error}</span>{persisted.recovery ? <><button onClick={() => session.restoreRecovery()}>恢复本机内容</button><button onClick={() => attempt(() => session.discardRecovery())}>使用服务端版本</button></> : status === "conflict" ? <><button onClick={() => attempt(() => session.saveAsNew())}>另存项目</button><button onClick={() => attempt(() => session.discardRecovery())}>重新载入服务端版本</button></> : <button onClick={() => attempt(() => !projectId ? session.initialize() : session.save())}>重试保存</button>}</div>}
    {persisted.backupUnavailable && status !== "saved" && <div className={styles.persistenceNotice}>本机备份不可用，请等待保存成功后离开页面。</div>}
    {library.error && screen !== "editing" && <div role="alert" className={styles.persistenceNotice}>{library.error}<button onClick={() => attempt(() => library.reload())}>重试读取数字人库</button></div>}
    {persisted.legacyAvailable && !blocked && <div className={styles.persistenceNotice}><span>发现此浏览器的旧演示记录</span><button onClick={() => attempt(() => session.importLegacy())}>导入本机旧记录</button></div>}
    <fieldset disabled={blocked} className={styles.persistenceBody}>{screen === "create" ? editor : <><header className={styles.header}>{screen === "editing" ? <div className={styles.editingTitle}><button type="button" onClick={() => go("home")}>返回</button><b>智能剪辑</b></div> : <Link href="/video-studio" aria-label="视频空间首页"><Brand /></Link>}<div className={styles.headerActions}>{credits.balance && <span className={styles.creditBalance} title="工作区可用积分">积分 {credits.balance.available.toLocaleString("zh-CN")}</span>}<TaskCenter userId={userId} workspaceId={workspaceId} jobs={library.jobs} notify={notify} /><span className={styles.previewBadge}>灰度测试</span><Link href="/" className={styles.returnSite}>返回极光商绘<ExternalLink size={14} /></Link><button type="button" className={styles.accountAvatar} onClick={() => open("help")} aria-label="灰度说明">极</button></div></header><div className={styles.workspace}><aside className={styles.sidebar}><Link href="/video-studio" className={`${styles.sideHome} ${screen === "home" ? styles.activeNav : ""}`}><FolderOpen size={18} />创作空间</Link>{navGroups.map(group => <div key={group.label} className={styles.navSection}><span className={styles.navGroup}>{group.label}</span><nav aria-label={group.label}>{group.items.map(item => <Link key={item.key} href={hrefOf(item.key) + (persisted.revision ? `?project=${projectId}` : "")} onClick={event => { event.preventDefault(); go(item.key); }} className={screen === item.key ? styles.activeNav : ""} aria-current={screen === item.key ? "page" : undefined}>{item.icon}<span>{item.label}</span></Link>)}</nav></div>)}<div className={styles.sidebarBottom}><div className={styles.sidePromo}><Sparkles size={20} /><b>每个好产品，都值得被看见</b><span>用数字人，讲述你的品牌故事。</span><button type="button" onClick={() => go("create")}>开始创作 <ArrowRight size={14} /></button></div><button type="button" className={styles.helpButton} onClick={() => open("help")}><CircleHelp size={17} />使用帮助<ExternalLink size={13} /></button></div></aside><main className={styles.main}>{screen === "writing" && stepBar("writing")}{screen === "editing" && stepBar("editing")}{screen === "writing" ? <WritingStudio workspaceId={workspaceId} projectId={projectId} session={session} content={content} writing={writing} savedTexts={copies.map(copy => copy.text)} notify={notify} attempt={attempt} copyText={copyText} updateDraft={updateDraft} onSaveToLibrary={saveCopy} onUseForVoice={() => go("create")} onUseScripts={openVoiceWith} /> : screen === "home" ? homeContent : screen === "avatars" || screen === "voices" ? assetContent : screen === "library" ? <ScriptLibraryPage workspaceId={workspaceId} notify={notify} copyText={copyText} onUseScripts={openVoiceWith} onWrite={() => go("writing")} /> : screen === "works" ? worksContent : <StudioEditingScreen cost={credits.note(["editing_planning", "editing_render"])} renderCredits={credits.note(["editing_render"]).credits} workspaceId={workspaceId} persisted={persisted} jobs={library.jobs} attempt={attempt} updateDraft={updateDraft} saveEditingProject={saveEditingProject} />}</main></div></>}

    </fieldset>
    {modal === "avatar-preview" && avatarPreview && <Dialog title={avatarPreview.name} onClose={() => setModal(null)}>{avatarPreview.preview_url ? <video controls playsInline preload="metadata" src={mediaUrl(avatarPreview.preview_url)} style={{ width: "100%", maxHeight: "60vh" }} /> : <img src={mediaUrl(imageOf(avatarPreview))} alt={avatarPreview.name} style={{ width: "100%", maxHeight: "60vh", objectFit: "contain" }} />}<p>{avatarPreview.source === "quanyu_public" ? "公共数字人，可直接用于口播生成" : avatarPreview.ready ? "极光原创数字人，动作模板已就绪" : "原创参考形象，生成动作模板后可用于口播"}</p><footer className={styles.dialogFooter}><button className={styles.primaryButton} onClick={() => { updateDraft({ avatarId: avatarPreview.id }); setModal(null); go("create"); }}>使用此形象</button></footer></Dialog>}
    {modal === "h3-template" && templateAvatar && <Dialog title="生成形象动作" onClose={() => setModal(null)}><div className={styles.templateReview}><img src={mediaUrl(imageOf(templateAvatar))} alt={templateAvatar.name} /><div><h3>{templateAvatar.name}</h3><span>10 秒 · 自然讲述动作</span></div></div><MetadataGrid items={[{label:"拍摄方式",value:"固定机位"},{label:"动作衔接",value:"正向首尾循环"}]} /><Notice>生成后先预览，确认人物与动作满意再加入形象库。</Notice><CostLine note={credits.note(["avatar_motion", "avatar_register"])} />{generationError && <Notice tone="warning">{generationError}</Notice>}<footer className={styles.dialogFooter}><button type="button" className={styles.outlineButton} onClick={() => setModal(null)}>取消</button><button type="button" className={styles.primaryButton} disabled={submitting || credits.note(["avatar_motion", "avatar_register"]).insufficient} onClick={createTemplate}>{submitting ? "正在提交" : generationError ? "再次确认（不会重复扣费）" : billableLabel("生成形象动作", credits.note(["avatar_motion"]).credits)}</button></footer></Dialog>}
    {modal === "real-preview" && realPreview && <GenerationPreview approveCost={credits.note(["avatar_register"])} job={realPreview} resuming={library.resumingIds.includes(realPreview.id)} submitting={submitting} onClose={() => setModal(null)} onResume={() => attempt(() => library.resume(realPreview.id))} onCopy={copyText} onUseAvatar={() => continueWithAvatar(realPreview)} onEdit={() => editGeneratedVideo(realPreview)} onApprove={() => attempt(async () => { setSubmitting(true); try { await library.approveTemplate(realPreview.id); } catch (error) { submissionError(error); } finally { setSubmitting(false); } })} onReject={() => attempt(async () => { setSubmitting(true); try { await library.rejectTemplate(realPreview.id); setModal(null); } finally { setSubmitting(false); } })} />}
    {modal === "proofread" && <ScriptProofread original={rawReference?.original_text || ""} text={draft.text} onChange={text => updateDraft({ text })} onClose={() => setModal(null)} onSave={() => attempt(async () => { await session.save(); setModal(null); notify("校对稿已保存，原始参考文稿保留"); })} />}
    {modal === "history" && <ScriptHistory workspaceId={workspaceId} versions={persisted.history} currentText={draft.text} saving={status === "saving"} onRestore={restoreVersion} onCopy={copyText} onClose={() => setModal(null)} />}
    {screen === "create" && <div className={styles.editorBrand}><Brand small /><span>灰度测试 · 仅指定账号可用</span></div>}
    {toast && <StudioToast message={toast} contextKey={modal} onClose={dismissToast} />}
    {modal === "avatar" && <AvatarPicker avatars={AVATARS} selectedId={selectedAvatar} loading={library.loading} error={library.error} onSelect={setSelectedAvatar} onApply={() => { if (AVATARS.some(item => item.id === selectedAvatar)) { updateDraft({ avatarId: selectedAvatar }); setModal(null); } }} onClose={() => setModal(null)} onReload={() => attempt(() => library.reload())} onClone={() => open("avatar-clone")} />}
    {modal === "voice" && <VoicePicker voices={VOICES.filter(item => item.available !== false)} selectedId={selectedVoice} playingId={playingVoice} onSelect={item => setSelectedVoice(item.id)} onPreview={previewVoice} onApply={() => { applyVoice(selectedVoice); setModal(null); }} onClose={() => setModal(null)} onClone={() => open("voice-clone")} />}

    {modal === "voice-clone" && <VoiceCloneDialog cost={credits.note(["voice_clone"])} clones={clones} onClose={() => { setModal(null); setAssetTab("own"); }} onCreated={() => { void library.reload(); setAssetTab("own"); }} />}
    {modal === "avatar-clone" && <AvatarCloneDialog costFor={kind => credits.note(kind === "image" ? ["avatar_motion", "avatar_register"] : ["avatar_register"])} motionCredits={credits.note(["avatar_motion"]).credits} library={library} userId={userId} workspaceId={workspaceId} onClose={() => setModal(null)} onCreated={job => { setAssetTab("own"); setRealPreview(job); setModal("real-preview"); setRightTab("works"); }} />}
    {modal === "generate" && <GenerationConfirmation cost={credits.note(["lipsync"])} draft={draft} avatar={avatar} voiceName={voice?.name} audioName={audio?.name} language={voice?.languages?.[draft.language || "auto"]} error={generationError} busy={submitting} saving={status === "saving"} onClose={() => setModal(null)} onConfirm={createRealVideo} onCopy={copyText} />}
    {modal === "preview" && previewWork && <Dialog title={previewWork.draft.name || "演示预览"} onClose={() => { setModal(null); window.speechSynthesis?.cancel(); setSpeaking(false); }}><div className={styles.demoPreview}><img src={mediaUrl(imageOf(AVATARS.find(item => item.id === previewWork.draft.avatarId) ?? AVATARS[0]))} alt="演示形象" /><span>静态形象预览 · 非生成视频</span></div><TextDocument text={previewWork.draft.drive === "audio" ? "音频驱动演示任务；音频只保留在原始会话中。" : previewWork.draft.text} title="演示文案" onCopy={copyText} /><footer className={styles.dialogFooter}><button className={styles.outlineButton} onClick={() => attempt(async () => { await session.select(previewWork.projectId); session.edit(previewWork.content); setModal(null); go("create"); })}>继续编辑</button>{previewWork.draft.drive === "text" && <button className={styles.primaryButton} onClick={() => audition(previewWork.draft.text)}><Volume2 size={16} />{speaking ? "停止试听" : "试听文案"}</button>}</footer></Dialog>}
    {modal === "help" && <Dialog title="开始你的视频创作" onClose={() => setModal(null)}><div className={styles.helpContent}><div className={styles.helpSteps}>{[{title:"写好文案",hint:"在爆款文案里找对标、改写并定稿，或直接粘贴已有文案"},{title:"生成口播",hint:"选择形象与声音，生成数字人口播"},{title:"智能剪辑",hint:"选模板生成预览，确认后下载高清"},{title:"查看作品",hint:"在我的作品里找回进行中和已完成的视频"}].map((step,index) => <div key={step.title}><span>{index + 1}</span><div><b>{step.title}</b><p>{step.hint}</p></div></div>)}</div><Disclosure title="创作须知" description="保存、素材与使用范围"><ul className={styles.helpNotes}><li>草稿、文案版本和任务保存在账号中。</li><li>采用文案前请核对产品事实。</li><li>声音克隆请使用本人录音，生成按实际服务计费。</li><li>智能剪辑支持字幕与组合动效，当前可用选项以项目界面为准。</li></ul></Disclosure><button type="button" className={styles.primaryButton} onClick={() => { setModal(null); go("writing"); }}>从文案开始 <ArrowRight size={16} /></button></div></Dialog>}
  </div>;
}
