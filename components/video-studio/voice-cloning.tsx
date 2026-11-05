"use client";
import { useRef, useState } from "react";
import { AudioLines, Mic, Upload } from "lucide-react";
import type { useVoiceClones } from "@/features/video-studio/voice-clones";
import { Dialog, Empty } from "./studio-primitives";
import styles from "./video-studio.module.css";
import cloneStyles from "./voice-cloning.module.css";
import { VoiceProgress } from "./voice-progress";
import type { UploadProgress } from "@/lib/api/upload";
type Clones = ReturnType<typeof useVoiceClones>;
const statusLabel: Record<string, string> = { queued: "等待处理", submitting: "正在创建", processing: "审核处理中", ready: "可以使用", unknown: "结果待核对", failed: "未通过，请检查录音" };

export function VoiceCloneDialog({ clones, onClose, onCreated }: { clones: Clones; onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState(""); const [file, setFile] = useState<File>();
  const [consent, setConsent] = useState(false); const [busy, setBusy] = useState(false);
  const [error, setError] = useState(""); const [submittedId, setSubmittedId] = useState("");
  const [upload, setUpload] = useState<UploadProgress>(); const [startedAt, setStartedAt] = useState<number>();
  const submitting = useRef(false);
  const submitted = clones.voices.find(voice => voice.id === submittedId);
  const requestId = useRef(""); const [attempted, setAttempted] = useState(false);
  const submit = async () => {
    if (!file || !name.trim() || !consent || submitting.current) return;
    submitting.current = true; setBusy(true); setAttempted(true); setError(""); setStartedAt(Date.now()); setUpload({ loaded: 0, complete: false }); requestId.current ||= crypto.randomUUID();
    try { const voice = await clones.create(file, name.trim(), requestId.current, setUpload); setSubmittedId(voice.id); onCreated(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "提交结果未确认，请先查看我的声音。"); void clones.reload().catch(() => undefined); }
    finally { submitting.current = false; setBusy(false); }
  };
  const processing = busy || !!submittedId;
  return <Dialog title="克隆我的声音" className={cloneStyles.cloneDialog} closeDisabled={busy} onClose={() => { if (!submitting.current) onClose(); }}>
    {processing ? <div className={cloneStyles.processing}>
      <VoiceProgress status={busy ? upload?.complete ? "validating" : "uploading" : submitted?.status || "queued"} upload={upload} startedAt={startedAt} />
      {clones.error && <p role="alert" className={cloneStyles.error}>{clones.error}</p>}
    </div> : <div className={cloneStyles.form}>
      <p className={cloneStyles.intro}>用一段录音，留下属于你的声音。</p>
      <label className={cloneStyles.field}><span>声音名称</span><input aria-label="声音名称" disabled={attempted} maxLength={30} placeholder="例如：我的口播声音" value={name} onChange={event => setName(event.target.value)} /></label>
      <div className={cloneStyles.recording}>
        <div className={cloneStyles.fieldHeading}><span>声音录音</span><small>建议 10～20 秒自然独白</small></div>
        <label className={`${cloneStyles.uploadArea} ${file ? cloneStyles.fileSelected : ""}`}>
          <span className={cloneStyles.uploadIcon}>{file ? <AudioLines size={23} /> : <Upload size={23} />}</span>
          <b>{file?.name || "点击上传录音"}</b>
          <span className={cloneStyles.uploadHint}>{file ? "已选择录音 · 点击可更换" : "安静环境，单人说话，不加背景音乐"}</span>
          <input aria-label="选择声音录音" type="file" disabled={attempted} accept=".mp3,.wav,.m4a,audio/mpeg,audio/wav,audio/mp4" onChange={event => {
            const value = event.target.files?.[0]; if (!value) return;
            if (!/\.(mp3|wav|m4a)$/i.test(value.name) || value.size > 10 * 1024 * 1024) { setError("请选择 10 MB 以内的 MP3、WAV 或 M4A 录音。"); return; }
            setFile(value); setError("");
          }} />
        </label>
        <p className={cloneStyles.fileHelp}>MP3、WAV、M4A · 5～60 秒 · 最大 10 MB</p>
      </div>
      <label className={cloneStyles.consent}><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} /><span>这是我本人的声音，我授权平台处理录音，创建专属声音并用于视频配音。</span></label>
      {!clones.config?.available && <p role="status" className={cloneStyles.error}>{clones.error || "专属声音暂不可用，请稍后再试。"}</p>}
    </div>}
    {error && <p role="alert" className={cloneStyles.error}>{error}</p>}
    <footer className={cloneStyles.footer}>
      {submittedId ? <>
        {submitted?.status === "unknown" && <button type="button" className={styles.outlineButton} onClick={() => { void clones.refresh(submitted).catch(() => setError("暂时无法查询，请稍后重试。")); }}>查询原任务</button>}
        <button type="button" className={styles.primaryButton} onClick={onClose}>查看我的声音</button>
      </> : <>
        <button type="button" className={styles.outlineButton} disabled={busy} onClick={onClose}>取消</button>
        <button type="button" className={styles.primaryButton} disabled={busy || !name.trim() || !file || !consent || !clones.config?.available} onClick={() => { void submit(); }}>{busy ? "处理中…" : attempted ? "核对原提交" : "创建声音"}</button>
      </>}
    </footer>
  </Dialog>;

}

export function MyVoices({ clones, onClone, onApply, onReload, onError }: { clones: Clones; onClone: () => void; onApply: (id: string) => void; onReload: () => Promise<unknown>; onError: (text: string) => void }) {
  const [busyId, setBusyId] = useState("");
  const run = async (id: string, task: () => Promise<unknown>) => { if (busyId) return; setBusyId(id); try { await task(); await onReload(); } catch (reason) { onError(reason instanceof Error ? reason.message : "操作未完成，请重试。"); } finally { setBusyId(""); } };
  return <div className={cloneStyles.manager}><div className={cloneStyles.toolbar}><p>专属声音仅在你的账号与当前工作区内可见。</p><button type="button" className={styles.textButton} disabled={!!busyId} onClick={() => { void run("reload", clones.reload); }}>刷新列表</button></div>{clones.error && <p role="alert">{clones.error}</p>}
    {!clones.voices.length ? <Empty icon={<Mic size={29} />} title="还没有你的专属声音" description="上传一段本人的清晰录音，创建你的视频配音声音。" action={<button type="button" className={styles.outlineButton} onClick={onClone}>克隆我的声音</button>} /> : <div className={cloneStyles.voices}>{clones.voices.map(voice => <article key={voice.id} className={cloneStyles.voice}>
      <div className={cloneStyles.heading}><AudioLines size={25} /><div><b>{voice.name}</b><p>{statusLabel[voice.status] || voice.status}</p></div></div>
      {["queued", "submitting", "processing", "unknown", "failed"].includes(voice.status) && <VoiceProgress status={voice.status} compact />}
      {voice.preview_url && <audio controls preload="none" src={voice.preview_url} aria-label={`${voice.name}的缓存试听`} />}
      {voice.preview_status === "unknown" && <p role="status">试听结果暂未确认，请稍后查看或联系客服。</p>}{voice.preview_status === "submitting" && <VoiceProgress status="submitting" preview compact />}
      <div className={cloneStyles.actions}><button type="button" className={styles.textButton} disabled={!!busyId || voice.status === "failed"} onClick={() => { void run(voice.id, () => clones.refresh(voice)); }}>查询状态</button>
        {voice.status === "ready" && <><button type="button" className={styles.outlineButton} disabled={!!busyId || !clones.config?.available || voice.preview_status === "unknown" || voice.preview_status === "submitting"} onClick={() => { void run(voice.id, () => clones.preview(voice)); }}>{busyId === voice.id ? "正在处理…" : voice.preview_status === "ready" ? "刷新试听" : "生成试听"}</button><button type="button" className={styles.primaryButton} disabled={!clones.config?.available} onClick={() => onApply(voice.id)}>用于视频</button></>}
      </div></article>)}</div>}
  </div>;
}
