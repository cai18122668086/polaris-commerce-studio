"use client";

import { useEffect, useRef, useState } from "react";
import type { ToastTone } from "@/components/video-studio/studio-toast";
import { useVideoAssistance, type AssistantMode } from "./assistance";
import type { VideoDraft } from "./projects";
import type { useProjectSession } from "./use-project-session";

type ProjectSession = ReturnType<typeof useProjectSession>["session"];
export type ReferenceDraft = { projectId: string; text: string; link: string; note?: string };

const uid = () => crypto.randomUUID();

/**
 * Copywriting state for one video project: the assistant's brief, reference
 * links and transcripts, and rewrite results. Kept out of the studio shell so
 * the writing workspace and the voice editor share one implementation.
 */
export function useScriptReference({ userId, workspaceId, projectId, session, notify, attempt, updateDraft, onAdopted }: {
  userId: string;
  workspaceId: string;
  projectId: string;
  session: ProjectSession;
  notify: (text: string, tone?: ToastTone) => void;
  attempt: (operation: () => Promise<unknown>) => void;
  updateDraft: (patch: Partial<VideoDraft>) => void;
  onAdopted: () => void;
}) {
  const assistance = useVideoAssistance(userId, workspaceId, projectId);
  const createJob = assistance.latest("create");
  const rewriteJob = assistance.latest("rewrite");
  const extractJob = assistance.latest("extract");
  const assistantResult = createJob?.status === "completed" ? createJob.result.script || "" : "";
  const appliedAssistance = useRef(new Set<string>());
  const [assistantPrompt, setAssistantPrompt] = useState("");
  const [assistantType, setAssistantType] = useState("产品介绍");
  const [assistantMode, setAssistantMode] = useState<AssistantMode>("create");
  const [referenceDraft, setReferenceDraft] = useState<ReferenceDraft>();
  const sourceText = referenceDraft?.projectId === projectId ? referenceDraft.text : "";
  const sourceLink = referenceDraft?.projectId === projectId ? referenceDraft.link : "";
  const setSourceText = (text: string) => setReferenceDraft(current => ({ ...current, projectId, text, link: current?.projectId === projectId ? current.link : "", note: current?.projectId === projectId ? current.note : undefined }));
  const setSourceLink = (link: string) => setReferenceDraft(current => ({ projectId, link, text: current?.projectId === projectId ? current.text : "" }));
  const [rewrittenDraft, setRewrittenDraft] = useState<{ projectId: string; text: string }>();
  const rewrittenText = rewrittenDraft?.projectId === projectId ? rewrittenDraft.text : "";
  const setRewrittenText = (text: string) => setRewrittenDraft({ projectId, text });
  const assistantJob = assistantMode === "create" ? createJob : assistantMode === "extract" ? extractJob : assistantMode === "rewrite" ? rewriteJob : undefined;

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
    updateDraft({ text }); onAdopted();
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

  return {
    assistance, assistantJob, assistantResult,
    assistantPrompt, setAssistantPrompt, assistantType, setAssistantType, assistantMode, setAssistantMode,
    setReferenceDraft, sourceText, setSourceText, sourceLink, setSourceLink,
    rewrittenText, setRewrittenText,
    generateCopy, runReference, adoptReference,
  };
}

export type ScriptReference = ReturnType<typeof useScriptReference>;
