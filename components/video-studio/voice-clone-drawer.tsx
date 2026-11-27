"use client";

import { useRef, useState } from "react";
import { AudioLines, Upload } from "lucide-react";
import type { UploadProgress } from "@/lib/api/upload";
import { billableLabel, useVideoCredits } from "@/features/video-studio/credits";
import type { ClonedVoice, useVoiceClones } from "@/features/video-studio/voice-clones";
import { voiceCloneGate } from "@/features/video-studio/persona-rules";
import { SideDrawer } from "./side-drawer";
import { VoiceProgress } from "./voice-progress";
import base from "./video-studio.module.css";
import styles from "./library-drawers.module.css";

type Clones = ReturnType<typeof useVoiceClones>;

/**
 * 克隆声音抽屉（契约 C4）。开关由后端 /voice-clone-config 的 available 决定（现有配置项，
 * 不新增 env）。关闭时只展示「暂未开通」，不会调用创建接口，也不扣费。
 * onCreated：克隆任务建立后回调一次（status 多为 queued/processing，完成后在「我的声音」可用）。
 */
export function VoiceCloneDrawer({ open, onClose, workspaceId, clones, onCreated, onUseSystemVoices }: { open: boolean; onClose: () => void; workspaceId: string; clones: Clones; onCreated?: (voice: ClonedVoice) => void; onUseSystemVoices?: () => void }) {
  const credits = useVideoCredits(workspaceId);
  const cost = credits.note(["voice_clone"]);
  const gate = voiceCloneGate(clones.config, clones.config !== undefined || !!clones.error);
  const [name, setName] = useState("");
  const [file, setFile] = useState<File>();
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [submittedId, setSubmittedId] = useState("");
  const [upload, setUpload] = useState<UploadProgress>();
  const [startedAt, setStartedAt] = useState<number>();
  const [attempted, setAttempted] = useState(false);
  const submitting = useRef(false);
  const requestId = useRef("");
  const submitted = clones.voices.find(voice => voice.id === submittedId);
  const submit = async () => {
    // 双保险：开关关闭时绝不发创建请求。
    if (!gate.open || !file || !name.trim() || !consent || submitting.current) return;
    submitting.current = true; setBusy(true); setAttempted(true); setError(""); setStartedAt(Date.now()); setUpload({ loaded: 0, complete: false }); requestId.current ||= crypto.randomUUID();
    try { const voice = await clones.create(file, name.trim(), requestId.current, setUpload); setSubmittedId(voice.id); onCreated?.(voice); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "提交结果未确认，请先查看「我的声音」，不会重复扣费。"); void clones.reload().catch(() => undefined); }
    finally { submitting.current = false; setBusy(false); }
  };
  const processing = busy || !!submittedId;

  const footer = !gate.open ? <>
    <button type="button" className={base.outlineButton} onClick={onClose}>知道了</button>
    {onUseSystemVoices && <button type="button" className={base.primaryButton} onClick={() => { onUseSystemVoices(); onClose(); }}>去选系统声音</button>}
  </> : processing ? <>
    {submitted?.status === "unknown" && <button type="button" className={base.outlineButton} onClick={() => { void clones.refresh(submitted).catch(() => setError("暂时无法查询，请稍后重试。")); }}>查询原任务</button>}
    <button type="button" className={base.primaryButton} disabled={busy} onClick={onClose}>{busy ? "上传中…" : "先关闭，稍后查看"}</button>
  </> : <>
    <span className={`${styles.footerNote} ${cost.insufficient ? styles.short : ""}`}>{cost.text}</span>
    <button type="button" className={base.outlineButton} onClick={onClose}>取消</button>
    <button type="button" className={base.primaryButton} disabled={!!cost.insufficient || !name.trim() || !file || !consent} onClick={() => void submit()}>{attempted ? "再次确认（不会重复扣费）" : billableLabel("创建声音", cost.credits)}</button>
  </>;

  return <SideDrawer open={open} title="克隆我的声音" description="用一段本人录音，生成专属配音声音。" onClose={onClose} closeDisabled={busy} footer={footer}>
    {!gate.open ? <section className={styles.closedPanel} role="status">
      <h3>{gate.title}</h3>
      {gate.detail && <p>{gate.detail}</p>}
    </section> : processing ? <section className={styles.progress} aria-live="polite">
      <VoiceProgress status={busy ? upload?.complete ? "validating" : "uploading" : submitted?.status || "queued"} upload={upload} startedAt={startedAt} />
      <p>克隆在后台进行，关闭抽屉不影响进度；完成后会出现在「我的声音」。</p>
      {clones.error && <p role="alert" className={styles.error}>{clones.error}</p>}
    </section> : <>
      <label className={styles.field}><span>声音名称</span><input aria-label="声音名称" disabled={attempted} maxLength={30} placeholder="例如：我的口播声音" value={name} onChange={event => setName(event.target.value)} /></label>
      <label className={styles.drop}>
        {file ? <AudioLines size={22} /> : <Upload size={22} />}
        <b>{file?.name || "上传一段录音"}</b>
        <small>{file ? "点击可更换" : "安静环境、单人说话、不加背景音乐，建议 10～20 秒自然独白"}</small>
        <input aria-label="选择声音录音" type="file" disabled={attempted} accept=".mp3,.wav,.m4a,audio/mpeg,audio/wav,audio/mp4" onChange={event => {
          const value = event.target.files?.[0]; if (!value) return;
          if (!/\.(mp3|wav|m4a)$/i.test(value.name) || value.size > 10 * 1024 * 1024) { setError("请选择 10 MB 以内的 MP3、WAV 或 M4A 录音。"); return; }
          setFile(value); setError("");
        }} />
      </label>
      <p className={styles.hint}>MP3、WAV、M4A · {clones.config?.min_seconds ?? 5}～{clones.config?.max_seconds ?? 60} 秒 · 最大 10 MB</p>
      <label className={styles.consent}><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} /><span>这是我本人的声音，我授权平台处理录音，创建专属声音并用于视频配音。</span></label>
    </>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
  </SideDrawer>;
}
