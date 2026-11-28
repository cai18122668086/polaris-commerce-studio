"use client";

import { useEffect, useRef, useState } from "react";
import { Check, LoaderCircle, Sparkles, Upload } from "lucide-react";
import { ApiError } from "@/lib/api/api-error";
import { mediaUrl } from "@/lib/api/base-url";
import type { UploadProgress } from "@/lib/api/upload";
import { billableLabel, useVideoCredits } from "@/features/video-studio/credits";
import type { GenerationJob, useVideoLibrary } from "@/features/video-studio/library";
import { AVATAR_PHASE_COPY, avatarPhase, type AvatarPhase } from "@/features/video-studio/persona-rules";
import { AvatarCheckButton } from "./avatar-check-button";
import { POLISH_DESCRIPTION_MAX, POLISH_PRESETS, polishDescriptionError, useAvatarPolish } from "@/features/video-studio/avatar-polish";
import { SideDrawer } from "./side-drawer";
import base from "./video-studio.module.css";
import styles from "./library-drawers.module.css";

/** 抽屉回调给外层的新形象。status 会随任务推进变化，外层以自己的形象列表为准。 */
export type CreatedAvatar = { id: string; name: string; status: AvatarPhase; job_id: string; cover_url: string | null };
type Library = ReturnType<typeof useVideoLibrary>;

/**
 * 定制形象抽屉（契约 C4）。形象库页和口播页共用。
 * - onCreated：素材提交成功、任务已建立时回调一次（此时形象「定制中」）。
 * - onReady：形象已加入形象库后，用户点「使用这个形象」时回调。
 * 抽屉关掉后任务继续跑，进度在「我的形象」和任务中心里看得到。
 */
export function AvatarCreateDrawer({ open, onClose, workspaceId, userId, library, onCreated, onReady }: { open: boolean; onClose: () => void; workspaceId: string; userId: string; library: Library; onCreated?: (avatar: CreatedAvatar) => void; onReady?: (avatar: CreatedAvatar) => void }) {
  const credits = useVideoCredits(workspaceId);
  const [kind, setKind] = useState<"image" | "video">("image");
  const [name, setName] = useState("");
  const [file, setFile] = useState<File>();
  const [preview, setPreview] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [upload, setUpload] = useState<UploadProgress>();
  const [error, setError] = useState("");
  const [jobId, setJobId] = useState("");
  const [acting, setActing] = useState(false);
  const requestId = useRef("");
  // AI 润色（可选，仅照片）：生成 2 张候选，选一张或继续用原图
  const polish = useAvatarPolish(workspaceId);
  const [polishOn, setPolishOn] = useState(false);
  const [polishText, setPolishText] = useState("");
  const [polishTouched, setPolishTouched] = useState(false);
  const [chosen, setChosen] = useState("original");
  const polishError = polishDescriptionError(polishText);
  const candidatesRef = useRef<HTMLDivElement>(null);
  const candidateCount = polish.candidates.length;
  // 候选一出来就滚到候选区，免得用户在长表单里找不到结果
  useEffect(() => { if (candidateCount) candidatesRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [candidateCount]);
  const polishCost = credits.note(["avatar_polish"]);
  const polishTotal = polishCost.credits === null ? null : polishCost.credits * 2;
  const chosenCandidate = polish.candidates.find(item => item.id === chosen && item.status === "ready");
  type CandidateView = { id: string; slot: number; status: string; image_url?: string | null; message?: string | null };
  const shownCandidates: CandidateView[] = polish.candidates.length ? polish.candidates : [{ id: "pending-1", slot: 1, status: "queued" }, { id: "pending-2", slot: 2, status: "queued" }];
  const pendingKey = `polaris-avatar-creation:${userId}:${workspaceId}`;
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  const job = library.jobs.find(item => item.id === jobId);
  const phase: AvatarPhase = busy ? "uploading" : avatarPhase(job);
  const avatar = library.avatars.find(item => item.id === job?.avatar_id);
  const created = (value: GenerationJob, status: AvatarPhase): CreatedAvatar => ({ id: value.avatar_id, name: name.trim() || avatar?.name || "我的形象", status, job_id: value.id, cover_url: library.avatars.find(item => item.id === value.avatar_id)?.cover_url || null });
  const cost = credits.note(kind === "image" ? ["avatar_motion", "avatar_register"] : ["avatar_register"]);
  const registerCost = credits.note(["avatar_register"]);
  const motionCredits = credits.note(["avatar_motion"]).credits;

  const reset = () => { setJobId(""); setFile(undefined); setPreview(""); setConsent(false); setAttempted(false); setUpload(undefined); setError(""); requestId.current = ""; polish.reset(); setChosen("original"); };
  const submit = async () => {
    if (busy || !file || !name.trim() || !consent) return;
    if (!requestId.current) {
      try { requestId.current = sessionStorage.getItem(pendingKey) || crypto.randomUUID(); sessionStorage.setItem(pendingKey, requestId.current); } catch { requestId.current ||= crypto.randomUUID(); }
    }
    const original = library.jobs.find(item => item.request_id === requestId.current);
    if (original) { try { sessionStorage.removeItem(pendingKey); } catch {} setJobId(original.id); onCreated?.(created(original, avatarPhase(original))); return; }
    setBusy(true); setAttempted(true); setError("");
    try {
      const source = kind === "image" && chosenCandidate ? await polish.toFile(chosenCandidate) : file;
      const result = await library.createAvatar(source, name.trim(), requestId.current, setUpload);
      try { sessionStorage.removeItem(pendingKey); } catch {}
      setJobId(result.id);
      onCreated?.(created(result, avatarPhase(result)));
    } catch (reason) {
      if (reason instanceof ApiError && reason.status && reason.status >= 400 && reason.status < 500 && reason.status !== 409) {
        requestId.current = ""; setAttempted(false); setUpload(undefined);
        try { sessionStorage.removeItem(pendingKey); } catch {}
        setError(reason.message);
      } else setError("网络中断，正在确认这次提交是否已到达，不会重复扣费。可以再点一次确认，或稍后在「我的形象」查看。");
    } finally { setBusy(false); }
  };
  const act = async (task: () => Promise<unknown>) => { if (acting) return; setActing(true); setError(""); try { await task(); } catch (reason) { setError(reason instanceof Error ? reason.message : "操作没有完成，请重试。"); } finally { setActing(false); } };
  const percent = upload?.total ? Math.min(100, Math.round(upload.loaded / upload.total * 100)) : undefined;
  const submitted = !!jobId || busy;

  const footer = submitted ? <>
    {phase === "review" && job && <>
      <span className={styles.footerNote}>{registerCost.text}</span>
      <button type="button" className={base.outlineButton} disabled={acting} onClick={() => void act(async () => { await library.rejectTemplate(job.id); reset(); })}>放弃，重新上传</button>
      <button type="button" className={base.primaryButton} disabled={acting || registerCost.insufficient} onClick={() => void act(() => library.approveTemplate(job.id))}>{acting ? "正在提交…" : billableLabel("确认加入形象库", registerCost.credits)}</button>
    </>}
    {phase === "ready" && job && <>
      <button type="button" className={base.outlineButton} onClick={onClose}>完成</button>
      {onReady && <button type="button" className={base.primaryButton} onClick={() => { onReady(created(job, "ready")); onClose(); }}>使用这个形象</button>}
    </>}
    {phase === "failed" && <button type="button" className={base.primaryButton} onClick={reset}>重新上传</button>}
    {["uploading", "generating", "registering", "unknown"].includes(phase) && <button type="button" className={base.outlineButton} disabled={busy} onClick={onClose}>{busy ? "上传中…" : "先关闭，稍后查看"}</button>}
  </> : <>
    <span className={`${styles.footerNote} ${cost.insufficient ? styles.short : ""}`}>{cost.text}</span>
    <button type="button" className={base.outlineButton} onClick={onClose}>取消</button>
    <button type="button" className={base.primaryButton} disabled={!file || !name.trim() || !consent || (kind === "image" && cost.insufficient) || polish.busy || polish.running} onClick={() => void submit()}>{attempted ? "再次确认（不会重复扣费）" : kind === "image" ? billableLabel("生成形象动作", motionCredits) : "上传并预览"}</button>
  </>;

  return <SideDrawer open={open} title="定制我的形象" description="一张清晰照片或一段自然出镜视频，生成你的专属数字人。" onClose={onClose} closeDisabled={busy} footer={footer}>
    {submitted ? <section className={styles.progress} aria-live="polite">
      <h3>{["uploading", "generating", "registering"].includes(phase) ? <LoaderCircle size={16} className={styles.spin} /> : phase === "ready" ? <Check size={16} /> : null}{AVATAR_PHASE_COPY[phase].title}</h3>
      {["uploading", "generating", "registering"].includes(phase) && <div className={styles.progressBar} role="progressbar" aria-label="定制进度" aria-valuetext={phase === "uploading" && percent !== undefined ? `${percent}%` : AVATAR_PHASE_COPY[phase].title}><i style={phase === "uploading" && percent !== undefined ? { width: `${percent}%`, animation: "none" } : undefined} /></div>}
      <p>{AVATAR_PHASE_COPY[phase].detail}</p>
      {phase === "pending_check" && job && <div className={styles.checkRow}><AvatarCheckButton jobId={job.id} check={library.checkResult} checking={library.resumingIds.includes(job.id)} className={base.outlineButton} noticeClassName={styles.checkNotice} /></div>}
      {phase === "review" && job?.video_url && <video controls playsInline preload="metadata" src={mediaUrl(job.video_url)} aria-label="形象动作预览" />}
      {phase === "ready" && avatar?.cover_url && <div className={styles.summary}><img src={mediaUrl(avatar.cover_url)} alt={avatar.name} /><div><b>{avatar.name}</b><span>已加入「我的形象」</span></div></div>}
    </section> : <>
      <div className={styles.field}><span>素材类型</span>
        <div className={styles.segmented} role="radiogroup" aria-label="素材类型">{(["image", "video"] as const).map(value => <button key={value} type="button" role="radio" aria-checked={kind === value} disabled={attempted} onClick={() => { if (kind === value) return; setKind(value); setFile(undefined); setPreview(""); setError(""); }}><b>{value === "image" ? "上传照片" : "上传视频"}</b><small>{value === "image" ? "由照片生成自然口播动作" : "保留你本人的出镜动作"}</small></button>)}</div>
      </div>
      <label className={styles.field}><span>形象名称</span><input aria-label="形象名称" value={name} disabled={attempted} maxLength={30} placeholder="例如：店长小林" onChange={event => setName(event.target.value)} /></label>
      <label className={styles.drop}>
        {file && preview ? kind === "image" ? <img src={preview} alt="所选照片" /> : <video src={preview} muted playsInline preload="metadata" /> : <Upload size={22} />}
        <b>{file?.name || (kind === "image" ? "选择一张清晰照片" : "选择一段出镜视频")}</b>
        <small>{file ? "点击可更换" : kind === "image" ? "正面或微侧脸、面部无遮挡、光线均匀；半身或全身" : "单人出镜、机位稳定、2～120 秒"}</small>
        <input aria-label={kind === "image" ? "选择形象照片" : "选择形象视频"} type="file" disabled={attempted} accept={kind === "image" ? ".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp" : ".mp4,.mov,.webm,video/mp4,video/quicktime,video/webm"} onChange={event => {
          const value = event.target.files?.[0]; if (!value) return;
          const valid = kind === "image" ? /\.(jpe?g|png|webp)$/i.test(value.name) : /\.(mp4|mov|webm)$/i.test(value.name);
          if (!valid || value.size > (kind === "image" ? 10 : 50) * 1024 * 1024) { setError(kind === "image" ? "请选择 10 MB 以内的 JPG、PNG 或 WebP 图片。" : "请选择 50 MB 以内的 MP4、MOV 或 WebM 视频。"); return; }
          setFile(value); setPreview(URL.createObjectURL(value)); setError(""); polish.reset(); setChosen("original");
        }} />
      </label>
      <p className={styles.hint}>{kind === "image" ? "JPG、PNG、WebP · 最大 10 MB · 边长至少 256 像素" : "MP4、MOV、WebM · 2～120 秒 · 最大 50 MB"}</p>
      <ol className={styles.steps} aria-label="定制流程">{[kind === "image" ? "上传照片" : "上传视频", kind === "image" ? "生成动作" : "检查素材", "预览确认", "加入形象库"].map((step, index) => <li key={step}><b>{index + 1}</b>{step}</li>)}</ol>
      <label className={styles.consent}><input type="checkbox" checked={consent} disabled={attempted} onChange={event => setConsent(event.target.checked)} /><span>这是我本人或已获授权的形象，我同意平台处理该素材并创建专属数字人。</span></label>
      {kind === "image" && <section className={styles.polish} aria-label="AI 润色">
        <label className={styles.polishToggle}><input type="checkbox" role="switch" checked={polishOn} disabled={attempted} onChange={event => { setPolishOn(event.target.checked); if (!event.target.checked) setChosen("original"); }} /><span><b><Sparkles size={14} />AI 润色（可选）</b><small>保持你本人的五官，只换穿着、场景和光线；生成 2 张候选，选一张再创建形象。</small></span></label>
        {polishOn && <>
          <label className={styles.field}><span>想要的样子</span><textarea aria-label="AI 润色描述" value={polishText} maxLength={POLISH_DESCRIPTION_MAX} disabled={attempted || polish.busy || polish.running} placeholder="例如：把我变成穿西装、站在门店里的店长，暖色自然光" onChange={event => setPolishText(event.target.value)} onBlur={() => setPolishTouched(true)} /></label>
          <div className={styles.presets} aria-label="示例描述">{POLISH_PRESETS.map(item => <button key={item.label} type="button" aria-pressed={polishText === item.description} disabled={attempted || polish.busy || polish.running} onClick={() => { setPolishText(item.description); setPolishTouched(true); }}>{item.label}</button>)}</div>
          {polishTouched && polishError && <p className={styles.error} role="alert">{polishError}</p>}
          <div className={styles.polishAction}>
            <span className={styles.footerNote}>{polishTotal === null ? polishCost.text : `每张 ${polishCost.credits} 积分，按实际生成张数扣，失败不扣`}</span>
            <button type="button" className={base.outlineButton} disabled={!file || !consent || !!polishError || polish.busy || polish.running || attempted} onClick={() => { setPolishTouched(true); setChosen("original"); void polish.generate(file!, polishText); }}>{polish.busy || polish.running ? <><LoaderCircle size={14} className={styles.spin} />正在润色…</> : billableLabel(polish.candidates.length ? "重新生成 2 张" : "生成 2 张候选", polishTotal)}</button>
          </div>
          {!consent && file && <p className={styles.hint}>先勾选上面的授权确认，再生成候选。</p>}
          {polish.error && <p className={styles.error} role="alert">{polish.error}</p>}
          {(polish.candidates.length > 0 || polish.busy) && <div ref={candidatesRef} className={styles.candidates} role="radiogroup" aria-label="选择用于创建形象的照片">
            <button type="button" role="radio" aria-checked={chosen === "original"} className={styles.candidate} disabled={attempted} onClick={() => setChosen("original")}>
              <span>{preview && <img src={preview} alt="原图" />}</span><b>原图</b>
            </button>
            {shownCandidates.map(item => <button key={item.id} type="button" role="radio" aria-checked={chosen === item.id} className={styles.candidate} disabled={attempted || item.status !== "ready"} onClick={() => setChosen(item.id)}>
              <span>{item.status === "ready" && item.image_url ? <img src={mediaUrl(item.image_url)} alt={`候选 ${item.slot}`} /> : <i className={styles.candidateState}>{item.status === "failed" ? (item.message || "没有生成成功，不扣费") : <><LoaderCircle size={16} className={styles.spin} />生成中，约 1 分钟</>}</i>}</span>
              <b>候选 {item.slot}</b>
            </button>)}
          </div>}
          {chosenCandidate && <p className={styles.hint}>将用「候选 {chosenCandidate.slot}」创建形象。不满意可以重新生成，或选回原图。</p>}
        </>}
      </section>}
    </>}
    {error && <p className={styles.error} role="alert">{error}</p>}
  </SideDrawer>;
}
