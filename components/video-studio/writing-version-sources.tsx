"use client";

import { useRef, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import styles from "./writing-workflow.module.css";

type Sources = components["schemas"]["WritingVersionSources"];

export function WritingVersionSources({ workspaceId, projectId, versionId, adoptionId }: {
  workspaceId: string;
  projectId: string;
  versionId: string;
  adoptionId: string;
}) {
  const [sources, setSources] = useState<Sources>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef(false);

  const load = async () => {
    if (pending.current) return;
    pending.current = true;
    setLoading(true);
    setError("");
    try {
      const result = unwrapApiResponse(await apiClient.GET(
        "/api/v1/video-studio/workspaces/{workspace_id}/projects/{project_id}/versions/{version_id}/writing-sources",
        {
          params: { path: { workspace_id: workspaceId, project_id: projectId, version_id: versionId } },
          signal: AbortSignal.timeout(12000),
        },
      ));
      if (result.origin.adoption_id !== adoptionId) throw new Error("采用记录已变化，请刷新后核对。");
      setSources(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "暂时无法读取该版写稿来源。");
    } finally {
      pending.current = false;
      setLoading(false);
    }
  };

  const labels = new Map(sources?.facts.facts.map(fact => [fact.id, fact.label]));
  const sentences = new Map(sources?.reference.sentences.map(sentence => [sentence.id, sentence.text]));
  const sections = new Map(sources?.analysis.sections.map(section => [section.id, section.function]));
  return <details className={styles.versionSources} onToggle={event => {
    if (event.currentTarget.open && !sources && !error) void load();
  }}>
    <summary>查看该版写稿来源</summary>
    {loading && <p role="status">正在核对该版资料…</p>}
    {error && <p role="alert">{error} <button type="button" onClick={() => void load()}>重试读取来源</button></p>}
    {sources && <section aria-label="该版已核对的写稿来源">
      <details><summary>参考原文</summary>
        <p className={styles.document}>{sources.reference.original_text}</p>
        {sources.reference.source_note && <p>{sources.reference.source_note}</p>}
        {sources.reference.source_url && <p>{sources.reference.source_url}</p>}
      </details>
      <details><summary>拆解报告</summary>
        <p>{sources.analysis.topic}</p>
        <ol>{sources.analysis.sections.map(section => <li key={section.id}>
          <b>{section.function}</b><p>{section.explanation}</p>
        </li>)}</ol>
        {sources.analysis.source_claims?.map((claim, index) => <p key={index}>「{claim.quote}」 · {claim.reason}</p>)}
        <ul>{sources.analysis.limitations.map((text, index) => <li key={index}>{text}</li>)}</ul>
      </details>
      <details><summary>事实卡</summary>
        <ul>{sources.facts.facts.map(fact => <li key={fact.id}>
          <b>{fact.label}</b> · {fact.status === "unknown" ? "未知" : fact.value}
          {fact.source_note && <p>{fact.source_note}</p>}
        </li>)}</ul>
        {!!sources.facts.forbidden_terms?.length && <p>禁词 · {sources.facts.forbidden_terms.join("、")}</p>}
      </details>
      <details open><summary>采用草稿与逐句事实</summary>
        <p>{sources.draft.title}</p>
        <ol>{sources.draft.sentences.map((line, index) => <li key={index}>
          {"reference_sentence_id" in line
            ? <small>原句 · {sentences.get(line.reference_sentence_id)}</small>
            : <small>段落功能 · {sections.get(line.analysis_section_id)}</small>}
          <p>{line.text}</p>
          <small>{line.fact_ids?.length ? line.fact_ids.map(id => labels.get(id) ?? id).join("、") : "本句无事实引用"}</small>
        </li>)}</ol>
      </details>
    </section>}
  </details>;
}
