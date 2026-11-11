"use client";

import Link from "next/link";
import { ApiError } from "@/lib/api/api-error";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine, ArrowLeft, ArrowRight, AudioLines, BookOpenText, Check,
  ChevronDown, CircleHelp, Clapperboard, ExternalLink, FileText,
  FolderOpen, Play, Plus, Search,
  Settings2, Sparkles, Upload, UserRound, UsersRound, Video, Volume2,
} from "lucide-react";
import styles from "./video-studio.module.css";
import { Brand, Dialog, Empty } from "./studio-primitives";
import { VoiceBrowser, VoicePicker } from "./voice-picker";
import { AvatarPicker } from "./avatar-picker";
import { AvatarCloneDialog } from "./avatar-cloning";
import { GenerationPreview } from "./generation-preview";
import { EditingWorkspace } from "./editing-workspace";
import { EditingWorks } from "./editing-works";
import { GenerationConfirmation } from "./generation-confirmation";
import { ScriptProofread } from "./script-proofread";
import { Disclosure, MetadataGrid, Notice, TextDocument } from "./studio-content";
import { GenerationWorkCard } from "./generation-work-card";
import { StudioIntro } from "./studio-intro";
import { ScriptAssistant } from "./script-assistant";
import { ScriptHistory } from "./script-history";
import { ScriptLibrary } from "./script-library";
import { StudioToast, type ToastMessage, type ToastTone } from "./studio-toast";
import { useAutoReveal } from "@/features/video-studio/use-auto-reveal";
import workflowStyles from "./studio-workflow.module.css";
import { MyVoices, VoiceCloneDialog } from "./voice-cloning";
import { useVoiceClones } from "@/features/video-studio/voice-clones";
import { useVideoAssistance, type AssistantMode } from "@/features/video-studio/assistance";
import { WritingWorkflow } from "./writing-workflow";
import { BenchmarkSearch } from "./benchmark-search";
import { useProjectSession } from "@/features/video-studio/use-project-session";
import { useVideoLibrary, type VideoAvatar, type GenerationJob } from "@/features/video-studio/library";
import type { VideoDraft, VideoContent, VideoVersion } from "@/features/video-studio/projects";

export type StudioScreen = "home" | "create" | "avatars" | "voices" | "library" | "works" | "editing";
type Avatar = VideoAvatar;
type Draft = VideoDraft;
type SavedCopy = { id: string; title: string; text: string; date: string };
type DemoWork = { id: string; draft: Draft; date: string; projectId: string; content: VideoContent };
type Modal = "avatar" | "voice" | "avatar-clone" | "voice-clone" | "generate" | "preview" | "help" | "history" | "avatar-preview" | "h3-template" | "real-preview" | "proofread" | null;

const EMPTY_DRAFT: Draft = { name: "未命名视频", text: "", avatarId: "", voiceId: "", speed: 1, emotion: "自然", language: "auto", quality: "1080P", drive: "text" };
const imageOf = (avatar: Avatar | undefined) => avatar?.cover_url || undefined;
const EMPTY_AVATAR: Avatar = { id: "", name: "请选择数字人", tag: "", gender: "未知", source: "quanyu_public", cover_url: "", ready: false };
const hrefOf = (screen: StudioScreen) => screen === "home" ? "/video-studio" : `/video-studio/${screen}`;
const dateLabel = (date: string) => new Date(date).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
const uid = () => crypto.randomUUID();

export function VideoStudio({ screen, userId, workspaceId }: { screen: StudioScreen; userId: string; workspaceId: string }) {
  const router = useRouter();
  const library = useVideoLibrary(workspaceId);
  const clones = useVoiceClones(workspaceId);
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
  const restorePending = () => {
    if (generationRequest.current) return;
    try {
      const raw = sessionStorage.getItem(pendingKey);
      if (raw) {
        const body = JSON.parse(raw) as Parameters<typeof library.submit>[0];
        if (["lipsync", "h3_template"].includes(body.kind) && typeof body.request_id === "string" && typeof body.avatar_id === "string") generationRequest.current = body;
      }
    } catch { /* In-memory retry still works if storage is unavailable. */ }
  };
  const clearPending = () => { generationRequest.current = undefined; setGenerationError(""); try { sessionStorage.removeItem(pendingKey); } catch {} };
  const persistPending = () => { try { sessionStorage.setItem(pendingKey, JSON.stringify(generationRequest.current)); } catch {} };
  const submissionError = (error: unknown) => {
    if (error instanceof ApiError && error.status && error.status >= 400 && error.status < 500) { clearPending(); notify(error.message); }
    else setGenerationError("提交结果尚未确认，请查询原提交，避免重复计费。");
  };
  const persisted = useProjectSession(userId, workspaceId);
  const { session, content, projectId, status } = persisted;
  const assistance = useVideoAssistance(userId, workspaceId, projectId);
  const createJob = assistance.latest("create");
  const rewriteJob = assistance.latest("rewrite");
  const extractJob = assistance.latest("extract");
  const assistantResult = createJob?.status === "completed" ? createJob.result.script || "" : "";
  const appliedAssistance = useRef(new Set<string>());
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
  const [assistantPrompt, setAssistantPrompt] = useState("");
  const [assistantType, setAssistantType] = useState("产品介绍");
  const [assistantMode, setAssistantMode] = useState<AssistantMode>("create");
  const [referenceDraft, setReferenceDraft] = useState<{ projectId: string; text: string; link: string; note?: string }>();
  const sourceText = referenceDraft?.projectId === projectId ? referenceDraft.text : "";
  const sourceLink = referenceDraft?.projectId === projectId ? referenceDraft.link : "";
  const setSourceText = (text: string) => setReferenceDraft(current => ({ ...current, projectId, text, link: current?.projectId === projectId ? current.link : "", note: current?.projectId === projectId ? current.note : undefined }));
  const setSourceLink = (link: string) => setReferenceDraft(current => ({ projectId, link, text: current?.projectId === projectId ? current.text : "" }));
  const [rewrittenDraft, setRewrittenDraft] = useState<{ projectId: string; text: string }>();
  const rewrittenText = rewrittenDraft?.projectId === projectId ? rewrittenDraft.text : "";
  const setRewrittenText = (text: string) => setRewrittenDraft({ projectId, text });
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
  useEffect(() => { voicePlayer.current?.pause(); void Promise.resolve().then(() => setPlayingVoice("")); }, [modal, screen]);

  const attempt = (operation: () => Promise<unknown>) => { void operation().catch(error => notify(error instanceof Error ? error.message : "操作未完成，请重试", "error")); };
  const go = (next: StudioScreen) => attempt(async () => { await session.save(); router.push(hrefOf(next) + (session.state.revision ? `?project=${session.state.projectId}` : "")); });
  const addReference = () => {
    if (sourceLink.trim()) {
      try {
        const url = new URL(sourceLink.trim());
        if (!["http:", "https:"].includes(url.protocol) || !url.hostname || url.username || url.password) throw new Error();
      } catch { notify("请输入不含账号密码的完整 http 或 https 链接"); return false; }
    }
    const reference = { id: uid(), kind: sourceLink.trim() ? "url" as const : "text" as const, url: sourceLink.trim(), original_text: sourceText, note: (referenceDraft?.projectId === projectId && referenceDraft.note) || "用户提供；尚未自动采集" };
    session.edit({ ...session.state.content, references: [reference, ...session.state.content.references].slice(0, 50) });
    return true;
  };
  const open = (next: Modal) => {
    restorePending();
    if (next === "generate" && generationRequest.current?.kind === "h3_template") { setTemplateAvatar(AVATARS.find(a => a.id === generationRequest.current?.avatar_id)); next = "h3-template"; }
    setGenerationError(generationRequest.current ? "存在尚未确认的提交，本次只查询原提交。" : "");
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
    setAssistantMode(mode); setRightTab("assistant");
    if (mode === "rewrite" && !sourceText.trim()) setSourceText(rawReference?.original_text || draft.text);
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
  const generateCopy = () => attempt(async () => {
    if (!assistantPrompt.trim()) return notify("先填写产品信息和创作要求");
    const target = session.state.projectId;
    await session.save();
    if (session.state.projectId !== target) return;
    await assistance.submit({ project_id: target, expected_revision: session.state.revision, kind: "create", brief: assistantPrompt, style: assistantType as "产品介绍" | "好物种草" | "知识分享" | "品牌故事" });
    notify("文案任务已提交，完成后请确认再采用");
  });
  const runReference = (kind: "extract" | "rewrite") => attempt(async () => {
    if (kind === "extract" && !sourceLink.trim()) return notify("请先粘贴视频链接");
    if (kind === "rewrite" && !sourceText.trim()) return notify("请先提取或粘贴原始文案");
    if (!addReference()) return;
    const target = session.state.projectId;
    await session.save();
    if (session.state.projectId !== target) return;
    await assistance.submit({ project_id: target, expected_revision: session.state.revision, kind, brief: "依据已确认产品事实，生成自然口播文案", style: "产品介绍", reference_id: session.state.content.references[0].id });
    notify(kind === "extract" ? "语音提取任务已提交" : "改写任务已提交");
  });
  const adoptReference = (original = false) => {
    const text = original ? sourceText : rewrittenText || sourceText;
    if (!text.trim()) return notify("请先提取或粘贴文案");
    if (text.length > 3000) return notify("原文超过3000字，请先明确选择要使用的片段；不会自动截断");
    if (!addReference()) return;
    updateDraft({ text }); setModal(null); revealScript();
    notify(original || !rewrittenText ? "原文已原样填入编辑器" : "改写稿已填入编辑器", "success");
  };
  useEffect(() => {
    const jobs = [rewriteJob, extractJob];
    void Promise.resolve().then(() => {
      for (const job of jobs) {
        if (!job || job.status !== "completed" || session.state.projectId !== job.project_id || appliedAssistance.current.has(job.id)) continue;
        appliedAssistance.current.add(job.id);
        if (job.kind === "rewrite" && job.result.script) setRewrittenDraft({ projectId: job.project_id, text: job.result.script });
        if (job.kind === "extract" && job.result.text && job.result.source_url) {
          setReferenceDraft({ projectId: job.project_id, text: job.result.text, link: job.result.source_url });
          const reference = { id: job.id, kind: "url" as const, url: job.result.source_url, original_text: job.result.text, note: "EveryInfra 语音转写；参考内容，需核对后改写" };
          if (!session.state.content.references.some(r => r.id === job.id)) session.edit({ ...session.state.content, references: [reference, ...session.state.content.references].slice(0, 50) });
        }
      }
    });
  }, [rewriteJob, extractJob, session]);

  const tabs = (items: { key: string; label: string }[], value: string, onChange: (key: string) => void) => <div className={styles.tabs}>{items.map(item => <button type="button" key={item.key} className={value === item.key ? styles.activeTab : ""} aria-pressed={value === item.key} onClick={() => onChange(item.key)}>{item.label}</button>)}</div>;
  const filters = (placeholder: string) => <div className={styles.filterRow}><div className={styles.pills}>{["全部", "男", "女"].map(item => <button type="button" key={item} aria-pressed={gender === item} className={gender === item ? styles.activePill : ""} onClick={() => setGender(item)}>{item === "全部" ? item : `${item}性`}</button>)}</div><label className={styles.search}><Search size={15} /><input aria-label={placeholder} placeholder={placeholder} value={search} onChange={event => setSearch(event.target.value)} /></label></div>;
  const avatarGrid = (inDialog = false) => <><div className={`${styles.avatarGrid} ${inDialog ? styles.modalGrid : ""}`}>{filteredAvatars.slice(0, visibleAvatarCount).map(item => <div key={item.id} className={`${styles.avatarCard} ${inDialog && selectedAvatar === item.id ? styles.selectedCard : ""}`}>
    <button type="button" className={styles.avatarImage} aria-label={`预览${item.name}`} onClick={() => { setAvatarPreview(item); setModal("avatar-preview"); }}><img src={imageOf(item)} alt={`${item.name}数字人形象`} loading="lazy" /><span className={styles.avatarTag}>{item.tag}</span><span className={styles.cardHover}><Play size={15} fill="currentColor" />预览形象</span></button>
    <div className={styles.avatarCaption}><strong>{avatarLabel(item)}</strong><span>{item.gender === "未知" ? item.tag : item.gender}</span><button type="button" className={styles.textButton} onClick={() => inDialog ? setSelectedAvatar(item.id) : selectAvatar(item)}>{inDialog ? (selectedAvatar === item.id ? "已选择" : "选择") : "使用"}</button>{item.source === "self_owned" && !item.ready && <button type="button" className={styles.textButton} onClick={() => { setTemplateAvatar(item); open("h3-template"); }}>生成动作模板</button>}</div>
  </div>)}</div>{filteredAvatars.length > 0 && <div ref={avatarLoadMoreRef} className={workflowStyles.galleryProgress} role="status">{hasMoreAvatars ? `已展示 ${visibleAvatarCount} / ${filteredAvatars.length}，向下浏览自动加载` : `已展示全部 ${filteredAvatars.length} 个形象`}</div>}</>;
  const voiceGrid = () => <VoiceBrowser voices={VOICES.filter(item => item.source !== "own")} selectedId={selectedVoice || draft.voiceId} playingId={playingVoice} onPreview={previewVoice} onSelect={item => { setSelectedVoice(item.id); applyVoice(item.id); go("create"); }} />;
  const copyList = (compact = false) => <ScriptLibrary copies={copies} compact={compact} keyword={search} onCopy={copyText} onCreate={() => go("create")} onUse={copy => { updateDraft({ text:copy.text, name:copy.title }); if (!compact) go("create"); notify("文案已填入编辑器"); }} />;
  const demoWorkList = (compact = false) => works.length ? <div className={`${styles.worksGrid} ${compact ? styles.compactWorks : ""}`}>{works.filter(work => work.draft.name.includes(compact ? "" : search)).map(work => {
    const model = AVATARS.find(item => item.id === work.draft.avatarId) ?? EMPTY_AVATAR;
    return <article className={styles.workCard} key={work.id}><button type="button" className={styles.workImage} onClick={() => { setPreviewWork(work); setModal("preview"); }}><img src={imageOf(model)} alt={model.name} /><span>本地演示</span><i><Play size={21} fill="currentColor" /></i></button><div><b>{work.draft.name}</b><time>{dateLabel(work.date)}</time><p>演示预览 · 尚未生成视频</p><button className={styles.textButton} onClick={() => attempt(async () => { await session.select(work.projectId); session.edit(work.content); await session.save(); go("create"); if (compact) setRightTab("assistant"); })}>继续编辑 <ArrowRight size={14} /></button></div></article>;
  })}</div> : <Empty icon={<Clapperboard size={29} />} title="你的作品将在这里出现" description="选择形象，写下文案，开始制作第一个视频。" action={!compact && <button className={styles.primaryButton} onClick={() => go("create")}>创作视频 <Plus size={16} /></button>} />;


  const workList = (compact = false) => {
    const matchingJobs = library.jobs.filter(job => compact || `${job.snapshot?.draft.name || ""} ${AVATARS.find(avatar => avatar.id === job.avatar_id)?.name || ""}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
    return <><div className={`${styles.worksGrid} ${compact ? styles.compactGenerationWorks : ""}`}>{matchingJobs.map(job => <GenerationWorkCard key={job.id} job={job} avatar={AVATARS.find(a => a.id === job.avatar_id) || EMPTY_AVATAR} onPreview={() => { setRealPreview(job); setModal("real-preview"); }} onResume={() => attempt(() => library.resume(job.id))} resuming={library.resumingIds.includes(job.id)} />)}</div>{!matchingJobs.length && !!library.jobs.length && !works.length && <Empty icon={<Search size={25} />} title="没有找到匹配作品" description="换一个视频名称或形象关键词试试。" />}{works.length > 0 ? demoWorkList(compact) : !library.jobs.length && demoWorkList(compact)}<button type="button" className={styles.textButton} onClick={() => attempt(() => library.reload())}>刷新任务</button></>;
  };

  const worksContent = <>
    <div className={styles.pageHeading}><div><h1>我的作品</h1><p>每一个好想法，都在这里留下作品。</p></div><button className={styles.primaryButton} onClick={() => go("create")}><Plus size={16} />创作视频</button></div>
    <div className={styles.listHeading}><b>全部作品</b><label className={styles.search}><Search size={15} /><input aria-label="搜索作品" placeholder="搜索作品" value={search} onChange={event => setSearch(event.target.value)} /></label></div>
    <EditingWorks userId={userId} workspaceId={workspaceId} keyword={search} />
    <section aria-label="生成作品">
      <div className={styles.sectionHeading}><h2>生成作品</h2><span>{library.jobs.length + works.length} 项</span></div>
      {workList()}
    </section>
  </>;

  const assistantJob = assistantMode === "create" ? createJob : assistantMode === "extract" ? extractJob : assistantMode === "rewrite" ? rewriteJob : undefined;
  const assistant = <ScriptAssistant benchmark={<BenchmarkSearch key={"benchmark-" + projectId} workspaceId={workspaceId} jobs={assistance.benchmarkJobs} extractions={assistance.benchmarkExtractions}
    extractBusy={assistance.busy("extract")}
    onSearch={async criteria => {
      const target = session.state.projectId;
      await session.save();
      if (session.state.projectId !== target) return;
      await assistance.submitBenchmark({ ...criteria, project_id: target, expected_revision: session.state.revision });
    }}
    onNext={assistance.nextBenchmarkPage} onResume={assistance.resume}
    onExtract={async items => {
      const target = session.state.projectId;
      await session.save();
      if (session.state.projectId !== target) return;
      await assistance.submitBenchmarkExtractions({ project_id: target, expected_revision: session.state.revision, items });
    }}
    onUse={(item, page) => {
      const note = "抖音对标「" + page.result.keyword + "」，搜索任务 " + page.id;
      setReferenceDraft({ projectId, link: item.source_url, text: "", note });
      showAssistant("extract", false);
      notify("已填入参考链接，可提取语音原文");
    }} />} workflow={<WritingWorkflow key={projectId} workspaceId={workspaceId} projectId={projectId} revision={session.state.revision} saved={session.state.status === "saved" && session.state.revision > 0} references={content.references} productFacts={content.product_facts} onApplied={async () => { await session.select(projectId); revealScript(); notify("已采用为新草稿，确认稿仍由原流程管理", "success"); }} />} mode={assistantMode} onModeChange={mode => showAssistant(mode, false)} prompt={assistantPrompt} onPromptChange={setAssistantPrompt} style={assistantType} onStyleChange={setAssistantType}
    facts={content.product_facts} onFactsChange={facts => session.edit({ ...session.state.content, product_facts: facts })}
    sourceLink={sourceLink} onSourceLinkChange={setSourceLink} sourceText={sourceText} onSourceTextChange={setSourceText}
    result={assistantMode === "create" ? assistantResult : rewrittenText} onResultChange={setRewrittenText}
    job={assistantJob} busy={assistantMode !== "benchmark" && assistance.busy(assistantMode)}
    onSubmit={() => {
      if (assistantMode === "create") generateCopy();
      if (assistantMode === "extract" || assistantMode === "rewrite") runReference(assistantMode);
    }}
    onResume={() => assistantJob && attempt(() => assistance.resume(assistantJob.id))} onCopy={copyText} onUseOriginal={() => adoptReference(true)}
    onUseResult={() => { if (assistantMode === "rewrite") return adoptReference(); if (assistantResult.length > 3000) return notify("文案超过3000字，请先明确选择要使用的片段；不会自动截断", "warning"); updateDraft({ text: assistantResult }); revealScript(); notify("已填入文案编辑区", "success"); }} />;

  const editor = <main className={styles.editor}>
    <section className={styles.editorMain} aria-label="视频编辑器"><header className={styles.editorHeader}><Link href={persisted.revision ? `/video-studio?project=${projectId}` : "/video-studio"} onClick={event => { event.preventDefault(); go("home"); }} className={styles.back} aria-label="返回视频空间"><ArrowLeft size={19} /></Link>{tabs([{ key: "text", label: "文本驱动" }, { key: "audio", label: "音频驱动" }], draft.drive, drive => updateDraft({ drive: drive as Draft["drive"] }))}<label className={styles.projectName}><span>视频名称</span><input aria-label="视频名称" value={draft.name} maxLength={80} onChange={event => updateDraft({ name: event.target.value })} /></label><select aria-label="切换视频项目" value={persisted.projects.some(p => p.id === projectId) ? projectId : ""} onChange={event => attempt(() => session.select(event.target.value))}><option value="" disabled>新项目</option>{persisted.projects.map(p => <option value={p.id} key={p.id}>{p.content.draft.name || "未命名视频"}</option>)}</select><button type="button" className={styles.textButton} onClick={() => attempt(() => session.newProject())}>新建</button><span role="status" aria-label="项目保存状态" className={styles.autosave}><Check size={12} />{!loaded ? "载入中" : status === "saved" ? "已保存" : status === "saving" ? "保存中" : status === "dirty" ? "待保存" : "未保存"}</span></header>
      <div className={styles.editorBody}><div className={styles.portraitColumn}><div className={styles.portrait}>{avatar.id ? <><img src={imageOf(avatar)} alt={avatarLabel(avatar)} /><span className={styles.portraitBadge}>{avatarLabel(avatar)} · {avatar.tag}</span><span className={styles.portraitRatio}>9:16</span></> : <div className={styles.portraitEmpty}><UserRound size={46} /><b>先选择出镜形象</b><span>公共模特，随时开始创作</span></div>}</div><button type="button" className={styles.selectAvatar} onClick={() => open("avatar")}><UsersRound size={17} />选择数字人<ChevronDown size={15} /></button><div className={styles.portraitNote}><Video size={13} /> 数字人口播视频</div></div>
        <div className={styles.scriptColumn}>{draft.drive === "text" ? <><button type="button" className={styles.voiceSelector} onClick={() => open("voice")}><span className={styles.voiceSelectorIcon}><AudioLines size={23} /></span><span><b>{voice?.name ?? "请选择声音"}</b><small>{voice ? `${voice.gender === "未知" ? "" : `${voice.gender}声 · `}${voice.tag}` : "让你的数字人拥有专属声音"}</small></span><ChevronDown size={16} /></button><div className={styles.voiceParams}><label className={styles.speed}><span>语速 <b>{draft.speed.toFixed(1)}×</b></span><input aria-label="语速" type="range" min="0.5" max="1.5" step="0.1" value={draft.speed} onChange={event => updateDraft({ speed: Number(event.target.value) })} /></label><label><span>情绪</span><select aria-label="情绪" value={draft.emotion} disabled={!voice || (voice.emotions?.length ?? 1) < 2} onChange={event => updateDraft({ emotion: event.target.value as Draft["emotion"] })}>{(voice?.emotions?.includes(draft.emotion) ? voice.emotions : [draft.emotion, ...(voice?.emotions || []).filter(e => e !== draft.emotion)]).map(emotion => <option key={emotion}>{emotion}</option>)}</select></label><label><span>语言</span><select aria-label="语言" value={draft.language || "auto"} disabled={!voice || Object.keys(voice.languages || {}).length < 2} onChange={event => updateDraft({ language: event.target.value })}>{Object.entries(voice?.languages || { auto: "自动识别文案语言" }).map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></label></div>
          <div className={styles.scriptBox}><div className={styles.scriptToolbar}><span>视频文案</span><button type="button" onClick={() => setModal("proofread")}>原文校对</button><button type="button" title="播放所选音色的固定短样片" onClick={() => voice ? previewVoice(voice) : open("voice")}><Volume2 size={15} />{playingVoice && playingVoice === voice?.id ? "停止试听" : "音色试听"}</button></div><textarea ref={scriptInputRef} aria-label="视频文案" value={draft.text} placeholder={"请输入你希望数字人讲述的内容…\n\n也可以使用文案助手，或从视频链接提取文案。"} maxLength={3000} onChange={event => updateDraft({ text: event.target.value })} /><span className={styles.wordCount}>{draft.text.length} / 3000</span></div><div className={styles.copyActions}><button type="button" onClick={() => showAssistant("benchmark")}><Search size={15} />找对标</button><button type="button" onClick={() => showAssistant("extract")}><ArrowDownToLine size={15} />视频提取</button><button type="button" onClick={() => showAssistant("rewrite")}><FileText size={15} />文案二创</button><button type="button" onClick={() => showAssistant("create")}><Sparkles size={15} />AI 文案创作</button><button type="button" onClick={() => attempt(async () => { await session.loadHistory(); setModal("history"); })}>文案版本</button><button type="button" onClick={saveCopy}><FolderOpen size={15} />存入文案库</button></div></> : <div className={styles.audioDrive}><span className={styles.bigIcon}><AudioLines size={37} /></span><h2>上传音频，驱动数字人</h2><p>使用已经录制好的声音，让数字人替你讲述。</p><label className={styles.uploadButton}><Upload size={16} />选择音频<input type="file" accept="audio/*" onChange={event => {
            const file = event.target.files?.[0]; if (!file) return;
            if (!file.type.startsWith("audio/")) { notify("请选择音频文件"); return; }
            if (file.size > 50 * 1024 * 1024) { notify("请选择 50 MB 以内的音频"); return; }
            if (audioUrl.current) URL.revokeObjectURL(audioUrl.current);
            const url = URL.createObjectURL(file); audioUrl.current = url; setAudio({ projectId, name: file.name, url }); updateDraft({ audioAssetId: null });
            const uploadProjectId = projectId;
            attempt(async () => { const uploaded = await library.uploadAudio(file); if (session.state.projectId === uploadProjectId) updateDraft({ audioAssetId: uploaded.id }); notify("音频已保存，可用于口型驱动"); });
            session.edit({ ...session.state.content, media: [{ id: uid(), kind: "audio", name: file.name, mime_type: file.type, size_bytes: file.size, availability: "local_only" }, ...session.state.content.media.filter(m => m.kind !== "audio")] });
          }} /></label>{draft.audioAssetId && !audio && <audio controls src={`/api/v1/video-studio/workspaces/${workspaceId}/audio-files/${draft.audioAssetId}`} />}{audio ? <div className={styles.audioFile}><b>{audio.name}</b><audio controls src={audio.url} /><small>上传完成后可跨设备继续使用</small></div> : <small>{draft.audioAssetId ? "音频已保存，可继续生成" : content.media.find(m => m.kind === "audio") ? `已关联 ${content.media.find(m => m.kind === "audio")?.name}，请重新选择原文件` : "支持 MP3、WAV、M4A · 最大 50 MB"}</small>}</div>}</div></div>
      <footer className={styles.editorFooter}><label><Settings2 size={15} /><select aria-label="视频清晰度" value="source" disabled title="按所选动作模板的原始分辨率交付"><option value="source">模板原始清晰度</option></select></label><button type="button" className={styles.generateButton} onClick={generate}><Video size={18} />生成视频</button><button type="button" className={styles.editLater} onClick={() => setRightTab("editing")}><Clapperboard size={15} />口播剪辑<small>字幕与动效</small></button></footer>
    </section>
    <aside ref={assistantPanelRef} className={styles.editorAside}><div className={styles.rightTabs} role="group" aria-label="创作工具">{[{ key: "works", label: "作品" }, { key: "library", label: "文案库" }, { key: "assistant", label: "文案助手" }, { key: "editing", label: "智能剪辑" }].map(item => <button type="button" key={item.key} className={rightTab === item.key ? styles.activeRightTab : ""} aria-pressed={rightTab === item.key} onClick={() => setRightTab(item.key)}>{item.label}</button>)}</div><div className={styles.rightContent}>{rightTab === "assistant" ? assistant : rightTab === "works" ? <div className={styles.workList}>{workList(true)}</div> : rightTab === "library" ? copyList(true) : <EditingWorkspace key={`${workspaceId}:${projectId}`} workspaceId={workspaceId} projectId={projectId} saved={Boolean(persisted.revision)} jobs={library.jobs} compact />}</div></aside>
  </main>;

  const cards = [
    { title: "形象克隆", copy: "让数字分身，替你出镜", icon: <UsersRound />, className: styles.featureAvatar, action: () => go("avatars") },
    { title: "声音克隆", copy: "复刻你的声音与表达", icon: <AudioLines />, className: styles.featureVoice, action: () => go("voices") },
    { title: "智能剪辑", copy: "让口播视频更出彩", icon: <Clapperboard />, className: styles.featureEdit, action: () => go("editing"), later: false },
    { title: "AI 创作中心", copy: "从一个想法，到一条视频", icon: <Sparkles />, className: styles.featureCreate, action: () => go("create") },
  ];
  const nav = [
    { key: "create" as const, label: "创作视频", icon: <Video size={18} /> },
    { key: "avatars" as const, label: "形象克隆", icon: <UserRound size={18} /> },
    { key: "voices" as const, label: "声音克隆", icon: <AudioLines size={18} /> },
    { key: "editing" as const, label: "智能剪辑", icon: <Clapperboard size={18} />, later: false },
    { key: "works" as const, label: "我的作品", icon: <ArrowDownToLine size={18} /> },
    { key: "library" as const, label: "文案库", icon: <BookOpenText size={18} /> },
  ];
  const homeContent = <><StudioIntro avatarCount={AVATARS.filter(a => a.ready).length} voiceCount={VOICES.length} onCreate={() => go("create")} /><div className={styles.featureCards}>{cards.map(card => <button key={card.title} type="button" className={`${styles.featureCard} ${card.className}`} onClick={card.action}><div><h2>{card.title}{card.later && <small>即将上线</small>}</h2><p>{card.copy}</p><span>立即体验 <ArrowRight size={14} /></span></div><i>{card.icon}</i></button>)}</div><div className={styles.sectionHeading}><div><h2>公共数字人</h2><span>选一个喜欢的形象，直接开始创作</span></div><span className={styles.subtleLabel}>公共数字人</span></div>{filters("搜索数字人")}{avatarGrid()}{!filteredAvatars.length && <Empty icon={<Search size={25} />} title="没有找到匹配的数字人" description="试试其他名字或筛选条件。" />}</>;
  const assetContent = <><div className={styles.pageHeading}><div><h1>{screen === "avatars" ? "形象克隆" : "声音克隆"}</h1><p>{screen === "avatars" ? "管理你的数字分身，为每个故事选择合适的讲述者。" : "一个熟悉的声音，让表达更有温度。"}</p></div><button type="button" className={styles.primaryButton} onClick={() => open(screen === "avatars" ? "avatar-clone" : "voice-clone")}><Plus size={17} />{screen === "avatars" ? "克隆新形象" : "克隆新声音"}</button></div>{tabs([{ key: "own", label: screen === "avatars" ? "我的定制" : "我的声音" }, { key: "public", label: screen === "avatars" ? "公共模特" : "系统声音" }], assetTab, setAssetTab)}{assetTab === "own" && screen === "voices" ? <MyVoices clones={clones} onClone={() => open("voice-clone")} onApply={id => attempt(async () => { await library.reload(); applyVoice(id); await session.save(); router.push(hrefOf("create") + "?project=" + session.state.projectId); })} onReload={library.reload} onError={text => notify(text, "error")} /> : <>{screen === "avatars" && filters("搜索数字人")}{screen === "avatars" ? avatarGrid() : <><p className={styles.inlineNote}>选择适合视频风格的声音，点击试听预览</p>{voiceGrid()}</>}</>}</>;

  const blocked = status === "loading" || Boolean(persisted.recovery) || (!projectId && Boolean(persisted.error));
  const restoreVersion = (version: VideoVersion) => attempt(async () => {
    await session.restoreVersion(version);
    setModal(null);
    notify("历史版本已恢复为当前草稿，原版本保留", "success");
  });
  return <div className={`${styles.studio} ${screen === "editing" ? styles.editingStudio : ""}`}>
    {(persisted.error || persisted.recovery) && <div role="alert" className={styles.persistenceNotice}><span>{persisted.recovery ? "发现本机未保存内容，请选择恢复或使用服务端版本。" : persisted.error}</span>{persisted.recovery ? <><button onClick={() => session.restoreRecovery()}>恢复本机内容</button><button onClick={() => attempt(() => session.discardRecovery())}>使用服务端版本</button></> : status === "conflict" ? <><button onClick={() => attempt(() => session.saveAsNew())}>另存项目</button><button onClick={() => attempt(() => session.discardRecovery())}>重新载入服务端版本</button></> : <button onClick={() => attempt(() => !projectId ? session.initialize() : session.save())}>重试保存</button>}</div>}
    {persisted.backupUnavailable && status !== "saved" && <div className={styles.persistenceNotice}>本机备份不可用，请等待保存成功后离开页面。</div>}
    {library.error && <div role="alert" className={styles.persistenceNotice}>{library.error}<button onClick={() => attempt(() => library.reload())}>重试读取数字人库</button></div>}
    {persisted.legacyAvailable && !blocked && <div className={styles.persistenceNotice}><span>发现此浏览器的旧演示记录</span><button onClick={() => attempt(() => session.importLegacy())}>导入本机旧记录</button></div>}
    <fieldset disabled={blocked} className={styles.persistenceBody}>{screen === "create" ? editor : <><header className={styles.header}><Link href="/video-studio" aria-label="视频空间首页"><Brand /></Link><div className={styles.headerActions}><span className={styles.previewBadge}><i />灰度测试</span><Link href="/" className={styles.returnSite}>返回极光商绘<ExternalLink size={14} /></Link><button type="button" className={styles.accountAvatar} onClick={() => open("help")} aria-label="灰度说明">极</button></div></header><div className={styles.workspace}><aside className={styles.sidebar}><Link href="/video-studio" className={`${styles.sideHome} ${screen === "home" ? styles.activeNav : ""}`}><FolderOpen size={18} />创作空间</Link><span className={styles.navGroup}>数字人创作</span><nav aria-label="视频空间导航">{nav.map(item => <Link key={item.key} href={hrefOf(item.key) + (persisted.revision ? `?project=${projectId}` : "")} onClick={event => { event.preventDefault(); go(item.key); }} className={screen === item.key ? styles.activeNav : ""}>{item.icon}<span>{item.label}</span>{item.later && <small>即将上线</small>}</Link>)}</nav><div className={styles.sidebarBottom}><div className={styles.sidePromo}><Sparkles size={20} /><b>每个好产品，都值得被看见</b><span>用数字人，讲述你的品牌故事。</span><button type="button" onClick={() => go("create")}>开始创作 <ArrowRight size={14} /></button></div><button type="button" className={styles.helpButton} onClick={() => open("help")}><CircleHelp size={17} />使用帮助<ExternalLink size={13} /></button></div></aside><main className={styles.main}>{screen === "home" ? homeContent : screen === "avatars" || screen === "voices" ? assetContent : screen === "library" ? <><div className={styles.pageHeading}><div><h1>文案库</h1><p>收藏好的表达，让下一次创作更轻松。</p></div><button className={styles.primaryButton} onClick={() => go("create")}><Plus size={16} />新建文案</button></div><div className={styles.listHeading}><b>全部文案 <small>{copies.length}</small></b><label className={styles.search}><Search size={15} /><input aria-label="搜索文案" placeholder="搜索文案" value={search} onChange={event => setSearch(event.target.value)} /></label></div>{copyList()}</> : screen === "works" ? worksContent : <><div className={styles.pageHeading}><div><h1>智能剪辑</h1><p>让讲述更生动，让创作更完整。</p></div></div><div className={styles.editorHeader}>
      <label className={styles.projectName}><span>剪辑项目名称</span><input aria-label="剪辑项目名称" value={draft.name} maxLength={80} onChange={event => updateDraft({ name: event.target.value })} /></label>
      <select aria-label="切换剪辑项目" value={persisted.projects.some(p => p.id === projectId) ? projectId : ""} onChange={event => attempt(() => session.select(event.target.value))}><option value="" disabled>新项目</option>{persisted.projects.map(p => <option value={p.id} key={p.id}>{p.content.draft.name || "未命名视频"}</option>)}</select>
      <button type="button" onClick={() => attempt(() => session.newProject())}>新建剪辑项目</button>
      {!persisted.revision && <button type="button" onClick={() => attempt(async () => { if (session.state.content.draft.name === "未命名视频") session.edit({ ...session.state.content, draft: { ...session.state.content.draft, name: "口播剪辑项目" } }); await session.save(); })}>保存剪辑项目</button>}
      <span role="status">{status === "saving" ? "保存中" : persisted.revision ? "已保存" : "先保存项目，再上传素材"}</span>
    </div><EditingWorkspace key={`${workspaceId}:${projectId}`} workspaceId={workspaceId} projectId={projectId} saved={Boolean(persisted.revision)} jobs={library.jobs} /></>}</main></div></>}

    </fieldset>
    {modal === "avatar-preview" && avatarPreview && <Dialog title={avatarPreview.name} onClose={() => setModal(null)}>{avatarPreview.preview_url ? <video controls playsInline preload="metadata" src={avatarPreview.preview_url} style={{ width: "100%", maxHeight: "60vh" }} /> : <img src={imageOf(avatarPreview)} alt={avatarPreview.name} style={{ width: "100%", maxHeight: "60vh", objectFit: "contain" }} />}<p>{avatarPreview.source === "quanyu_public" ? "公共数字人，可直接用于口播生成" : avatarPreview.ready ? "极光原创数字人，动作模板已就绪" : "原创参考形象，生成动作模板后可用于口播"}</p><footer className={styles.dialogFooter}><button className={styles.primaryButton} onClick={() => { updateDraft({ avatarId: avatarPreview.id }); setModal(null); go("create"); }}>使用此形象</button></footer></Dialog>}
    {modal === "h3-template" && templateAvatar && <Dialog title="生成形象动作" onClose={() => setModal(null)}><div className={styles.templateReview}><img src={imageOf(templateAvatar)} alt={templateAvatar.name} /><div><h3>{templateAvatar.name}</h3><span>15 秒 · 自然讲述动作</span></div></div><MetadataGrid items={[{label:"拍摄方式",value:"固定机位"},{label:"动作衔接",value:"正向首尾循环"}]} /><Notice>生成后先预览，确认人物与动作满意再加入形象库。</Notice>{generationError && <Notice tone="warning">{generationError}</Notice>}<footer className={styles.dialogFooter}><button type="button" className={styles.outlineButton} onClick={() => setModal(null)}>取消</button><button type="button" className={styles.primaryButton} disabled={submitting} onClick={createTemplate}>{submitting ? "正在提交" : generationError ? "查询原提交" : "确认生成"}</button></footer></Dialog>}
    {modal === "real-preview" && realPreview && <GenerationPreview job={realPreview} resuming={library.resumingIds.includes(realPreview.id)} submitting={submitting} onClose={() => setModal(null)} onResume={() => attempt(() => library.resume(realPreview.id))} onCopy={copyText} onApprove={() => attempt(async () => { setSubmitting(true); try { await library.approveTemplate(realPreview.id); setModal(null); } catch (error) { submissionError(error); } finally { setSubmitting(false); } })} onReject={() => attempt(async () => { setSubmitting(true); try { await library.rejectTemplate(realPreview.id); setModal(null); } finally { setSubmitting(false); } })} />}
    {modal === "proofread" && <ScriptProofread original={rawReference?.original_text || ""} text={draft.text} onChange={text => updateDraft({ text })} onClose={() => setModal(null)} onSave={() => attempt(async () => { await session.save(); setModal(null); notify("校对稿已保存，原始参考文稿保留"); })} />}
    {modal === "history" && <ScriptHistory workspaceId={workspaceId} versions={persisted.history} currentText={draft.text} saving={status === "saving"} onRestore={restoreVersion} onCopy={copyText} onClose={() => setModal(null)} />}
    {screen === "create" && <div className={styles.editorBrand}><Brand small /><span>灰度测试 · 仅指定账号可用</span></div>}
    {toast && <StudioToast message={toast} contextKey={modal} onClose={dismissToast} />}
    {modal === "avatar" && <AvatarPicker avatars={AVATARS} selectedId={selectedAvatar} loading={library.loading} error={library.error} onSelect={setSelectedAvatar} onApply={() => { if (AVATARS.some(item => item.id === selectedAvatar)) { updateDraft({ avatarId: selectedAvatar }); setModal(null); } }} onClose={() => setModal(null)} onReload={() => attempt(() => library.reload())} onClone={() => open("avatar-clone")} />}
    {modal === "voice" && <VoicePicker voices={VOICES} selectedId={selectedVoice} playingId={playingVoice} onSelect={item => setSelectedVoice(item.id)} onPreview={previewVoice} onApply={() => { applyVoice(selectedVoice); setModal(null); }} onClose={() => setModal(null)} onClone={() => open("voice-clone")} />}

    {modal === "voice-clone" && <VoiceCloneDialog clones={clones} onClose={() => { setModal(null); setAssetTab("own"); }} onCreated={() => { void library.reload(); setAssetTab("own"); }} />}
    {modal === "avatar-clone" && <AvatarCloneDialog library={library} userId={userId} workspaceId={workspaceId} onClose={() => setModal(null)} onCreated={job => { setAssetTab("own"); setRealPreview(job); setModal("real-preview"); setRightTab("works"); }} />}
    {modal === "generate" && <GenerationConfirmation draft={draft} avatar={avatar} voiceName={voice?.name} audioName={audio?.name} language={voice?.languages?.[draft.language || "auto"]} error={generationError} busy={submitting} saving={status === "saving"} onClose={() => setModal(null)} onConfirm={createRealVideo} onCopy={copyText} />}
    {modal === "preview" && previewWork && <Dialog title={previewWork.draft.name || "演示预览"} onClose={() => { setModal(null); window.speechSynthesis?.cancel(); setSpeaking(false); }}><div className={styles.demoPreview}><img src={imageOf(AVATARS.find(item => item.id === previewWork.draft.avatarId) ?? AVATARS[0])} alt="演示形象" /><span>静态形象预览 · 非生成视频</span></div><TextDocument text={previewWork.draft.drive === "audio" ? "音频驱动演示任务；音频只保留在原始会话中。" : previewWork.draft.text} title="演示文案" onCopy={copyText} /><footer className={styles.dialogFooter}><button className={styles.outlineButton} onClick={() => attempt(async () => { await session.select(previewWork.projectId); session.edit(previewWork.content); setModal(null); go("create"); })}>继续编辑</button>{previewWork.draft.drive === "text" && <button className={styles.primaryButton} onClick={() => audition(previewWork.draft.text)}><Volume2 size={16} />{speaking ? "停止试听" : "试听文案"}</button>}</footer></Dialog>}
    {modal === "help" && <Dialog title="开始你的视频创作" onClose={() => setModal(null)}><div className={styles.helpContent}><div className={styles.helpSteps}>{[{title:"选择形象",hint:"使用公共模特或你的数字分身"},{title:"准备文案",hint:"原创、改写或提取后校对"},{title:"确定声音",hint:"选择音色，调整语速与情绪"},{title:"生成视频",hint:"在我的作品查看进度与结果"}].map((step,index) => <div key={step.title}><span>{index + 1}</span><div><b>{step.title}</b><p>{step.hint}</p></div></div>)}</div><Disclosure title="创作须知" description="保存、素材与使用范围"><ul className={styles.helpNotes}><li>草稿、文案版本和任务保存在账号中。</li><li>采用文案前请核对产品事实。</li><li>声音克隆请使用本人录音，生成按实际服务计费。</li><li>口播剪辑支持字幕与组合动效，当前可用选项以项目界面为准。</li></ul></Disclosure><button type="button" className={styles.primaryButton} onClick={() => { setModal(null); go("create"); }}>开始创作 <ArrowRight size={16} /></button></div></Dialog>}
  </div>;
}
