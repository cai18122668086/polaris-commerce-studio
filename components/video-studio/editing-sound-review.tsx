"use client";

import { useRef, useState } from "react";
import type { components } from "@/lib/api/generated/openapi";
import styles from "./editing-workspace.module.css";

type Artifact = components["schemas"]["EditingArtifactResponse"];
type Cue = { assetId: string; start: number; end?: number; label: string };
const phases = new Map([
  ["entry", "入场"], ["settle", "落定"], ["exit", "退场"], ["handoff", "衔接"],
]);

function readCues(value: unknown, durationMs: number | null): Cue[] {
  if (!value || typeof value !== "object") throw new Error("Invalid audio receipt");
  const report = value as Record<string, unknown>;
  const duration = durationMs === null ? Infinity : durationMs / 1000;
  const time = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && v >= 0;
  const cues: Cue[] = [];
  for (const kind of ["fx", "music"] as const) {
    const rows = report[kind];
    const music = kind === "music";
    if (!Array.isArray(rows) || rows.length > (music ? 8 : 120)) throw new Error("Invalid audio cues");
    for (const row of rows as unknown[]) {
      if (!row || typeof row !== "object") throw new Error("Invalid audio cue");
      const item = row as Record<string, unknown>;
      const assetId = item.asset_id;
      const start = music ? item.start_seconds : item.effective_onset_seconds;
      const end = item.end_seconds;
      const pattern = music ? /^bgm-[a-f0-9]{16}$/ : /^sfx-[a-f0-9]{16}$/;
      if (typeof assetId !== "string" || !pattern.test(assetId) || !time(start) || start >= duration) {
        throw new Error("Invalid audio cue time or source");
      }
      if (music) {
        if (!time(end) || end <= start || end > duration) throw new Error("Invalid music range");
        cues.push({ assetId, start, end, label: "背景乐" });
      } else {
        const phase = typeof item.phase === "string" ? phases.get(item.phase) : undefined;
        const group = typeof item.group_id === "string" ? item.group_id : "原生动效";
        cues.push({ assetId, start, label: phase ? `${group} · ${phase}音效` : `${group} · 音效` });
      }
    }
  }
  return cues.sort((a, b) => a.start - b.start);
}

export function EditingSoundReview({ workspaceId, receipt, media, playerId }: {
  workspaceId: string; receipt: Artifact; media: Artifact; playerId: string;
}) {
  const [cues, setCues] = useState<Cue[]>();
  const [loadError, setLoadError] = useState(false);
  const [playError, setPlayError] = useState("");
  const [original, setOriginal] = useState<number>();
  const loading = useRef(false);
  const audio = useRef<HTMLAudioElement>(null);
  const player = () => document.getElementById(playerId) as HTMLVideoElement | null;

  const load = async () => {
    if (loading.current) return;
    loading.current = true;
    setLoadError(false);
    try {
      const response = await fetch(receipt.url, { mode: "same-origin", signal: AbortSignal.timeout(12000) });
      if (!response.ok) throw new Error("Audio receipt unavailable");
      setCues(readCues(await response.json(), media.duration_ms));
    } catch {
      setLoadError(true);
    } finally {
      loading.current = false;
    }
  };

  const play = async (cue: Cue) => {
    const video = player();
    if (!video) return;
    audio.current?.pause();
    setPlayError("");
    try {
      video.currentTime = Math.max(0, cue.start - (cue.end === undefined ? 0.7 : 0));
      video.scrollIntoView({ block: "center" });
      await video.play();
    } catch {
      setPlayError("播放未开始，请用视频播放器重试。");
    }
  };

  return <details className={styles.filmReview} onToggle={event => {
    if (!event.currentTarget.open) audio.current?.pause();
    else if (!cues && !loadError) void load();
  }}>
    <summary>按点位试听音效与配乐</summary>
    <fieldset className={styles.correction}>
      <legend>本版混音点位</legend>
      <p className={styles.note}>音效时间取自原生混音回执。定位时提前约 0.7 秒播放，便于核对动作和起音。</p>
      {!cues && !loadError && <p role="status">正在读取声音校验记录…</p>}
      {loadError && <p role="alert">暂时无法读取本版混音点位。 <button type="button" onClick={() => void load()}>重试读取</button></p>}
      {playError && <p className={styles.error} role="alert">{playError}</p>}
      {cues?.length === 0 && <p className={styles.note}>本版声音记录没有音效或配乐点位。</p>}
      {!!cues?.length && <ol className={styles.materialList}>
        {cues.map((cue, i) => <li key={i}>
          <span>{cue.label} · <time>{cue.start.toFixed(3)} 秒</time>{cue.end !== undefined && ` 至 ${cue.end.toFixed(3)} 秒`}</span>
          <div className={styles.correctionActions}>
            <button type="button" onClick={() => void play(cue)}>定位试听混音</button>
            <button type="button" aria-expanded={original === i} onClick={() => {
              setPlayError("");
              setOriginal(original === i ? undefined : i);
            }}>{original === i ? "收起原包音频" : "打开原包音频"}</button>
          </div>
          {original === i && <audio ref={audio} controls preload="none" aria-label={`${cue.label}原包音频`}
            src={`/api/v1/video-studio/workspaces/${encodeURIComponent(workspaceId)}/editing-library/assets/${cue.assetId}/audio`}
            onPlay={() => player()?.pause()} onError={() => setPlayError("原包音频暂不可用，请检查资源完整性。")} />}
        </li>)}
      </ol>}
      <a href={receipt.url} download>下载声音校验记录</a>
    </fieldset>
  </details>;
}
