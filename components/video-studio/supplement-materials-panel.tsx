"use client";

// 剪辑第 ③ 步「补充素材」面板（契约 C5，W4）。默认不加素材；四条路可多选组合。
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type DragEvent } from "react";
import { Check, FileVideo, ImageIcon, RefreshCw, Trash2, Upload } from "lucide-react";
import { mediaUrl } from "@/lib/api/base-url";
import {
  aiCost,
  licenceLine,
  setMgStyle,
  setMode,
  setPending,
  setPin,
  setPlacement,
  setSourceMaterials,
  sourceBlocker,
  splitSentences,
  SOURCE_COPY,
  SOURCE_ORDER,
  STYLE_COPY,
  toggleSource,
  type AiEstimateResponse,
  type AiImageRow,
  type MaterialRow,
  type SourcesResponse,
  type StockSearchResponse,
  type SupplementMaterialsValue,
  type SupplementSourceKey,
  type SupplementStyle,
  type SupplementWorkItem,
} from "@/features/video-studio/supplement-materials";
import {
  aiImageStatus,
  createAiImages,
  deleteMaterial,
  estimateAiImages,
  fetchSources,
  importStock,
  listMaterials,
  placeMaterial,
  regenerateAiImage,
  searchStock,
  stockThumbUrl,
  uploadMaterial,
} from "@/features/video-studio/supplement-materials-api";
import styles from "./supplement-materials.module.css";

type Upload = { id: string; name: string; percent: number; error?: string };
type Props = {
  workspaceId: string;
  value: SupplementMaterialsValue;
  onChange: (value: SupplementMaterialsValue) => void;
  workItems: SupplementWorkItem[];
};

const MEDIA = /\.(jpe?g|png|webp|mp4|mov|webm)$/i;
const message = (error: unknown, fallback: string) => {
  const text = (error as { message?: string } | null)?.message;
  return text && /[一-鿿]/.test(text) ? text : fallback;
};

export function SupplementMaterialsPanel({ workspaceId, value, onChange, workItems }: Props) {
  const [sources, setSources] = useState<SourcesResponse>();
  const [sourcesError, setSourcesError] = useState("");
  const [activeId, setActiveId] = useState(workItems[0]?.id ?? "");
  const latest = useRef(value);
  useEffect(() => { latest.current = value; }, [value]);
  const update = useCallback((change: (current: SupplementMaterialsValue) => SupplementMaterialsValue) => {
    const next = change(latest.current);
    latest.current = next;
    onChange(next);
  }, [onChange]);

  useEffect(() => {
    let live = true;
    fetchSources(workspaceId).then(data => { if (live) setSources(data); }).catch(() => { if (live) setSourcesError("暂时读不到素材来源，稍后再试。"); });
    return () => { live = false; };
  }, [workspaceId]);
  const active = workItems.find(item => item.id === activeId) ?? workItems[0];
  const blockers = useMemo(() => Object.fromEntries(
    SOURCE_ORDER.map(key => [key, sources ? sourceBlocker(key, workItems, sources.sources) : null]),
  ) as Record<SupplementSourceKey, string | null>, [sources, workItems]);
  const state = (key: SupplementSourceKey) => sources?.sources.find(row => row.key === key);
  const pendingBy = useRef<Record<string, number>>({});
  const report = useCallback((key: string, count: number) => {
    pendingBy.current[key] = count;
    const total = Object.values(pendingBy.current).reduce((sum, n) => sum + n, 0);
    update(current => setPending(current, total));
  }, [update]);

  const custom = value.mode === "custom";
  const enabled = (key: SupplementSourceKey) => Boolean(custom && value.sources[key]?.enabled);

  return (
    <section className={styles.panel} aria-labelledby="supplement-title">
      <header className={styles.head}>
        <h3 id="supplement-title">补充素材</h3>
        <p>可选。不选就只用口播原片和模板自带的画面。</p>
      </header>

      <div className={styles.mode} role="radiogroup" aria-label="是否补充素材">
        {(["none", "custom"] as const).map(mode => (
          <label key={mode} className={styles.modeOption} data-checked={value.mode === mode}>
            <input type="radio" name="supplement-mode" checked={value.mode === mode} onChange={() => update(current => setMode(current, mode))} />
            <span>
              <b>{mode === "none" ? "不加素材" : "补充素材"}</b>
              <small>{mode === "none" ? "默认。成片里不会出现额外的图片、视频或动效" : "从下面四种方式里选，可以组合"}</small>
            </span>
          </label>
        ))}
      </div>

      {custom && (
        <>
          {sourcesError && <p className={styles.error}>{sourcesError}</p>}
          <div className={styles.cards}>
            {SOURCE_ORDER.map(key => {
              const blocked = sources ? blockers[key] : "正在读取…";
              const info = state(key);
              const checked = enabled(key);
              const price = key === "ai_image"
                ? (info?.credits_per_image ? `${info.credits_per_image} 积分/张，每条最多 ${info.max_images ?? 6} 张` : "按实际张数计费")
                : "免费";
              return (
                <label key={key} className={styles.card} data-checked={checked} data-disabled={Boolean(blocked)}>
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={Boolean(blocked)}
                    onChange={event => update(current => toggleSource(current, key, event.target.checked, Math.min(4, info?.max_images ?? 4)))}
                  />
                  <span className={styles.cardBody}>
                    <b>{SOURCE_COPY[key].title}</b>
                    <span>{SOURCE_COPY[key].line}</span>
                    <small>{blocked ?? price}</small>
                  </span>
                  <span className={styles.tick} aria-hidden>{checked && <Check size={13} strokeWidth={2.4} />}</span>
                </label>
              );
            })}
          </div>

          {workItems.length > 1 && (value.sources.mine?.enabled || value.sources.stock?.enabled || value.sources.ai_image?.enabled) && (
            <nav className={styles.items} aria-label="按视频查看素材">
              {workItems.map((item, index) => (
                <button key={item.id} type="button" aria-pressed={item.id === active?.id} onClick={() => setActiveId(item.id)}>
                  {item.title?.trim() || `视频 ${index + 1}`}
                  <small>{value.items[item.id]?.material_ids.length ?? 0}</small>
                </button>
              ))}
            </nav>
          )}

          {active && enabled("mine") && (
            <MineSection key={`mine-${active.id}`} workspaceId={workspaceId} item={active} value={value} update={update} report={report} />
          )}
          {active && enabled("stock") && (
            <StockSection key={`stock-${active.id}`} workspaceId={workspaceId} item={active} value={value} update={update} report={report} sources={sources} />
          )}
          {active && enabled("ai_image") && (
            <AiSection key={`ai-${active.id}`} workspaceId={workspaceId} item={active} value={value} update={update} report={report} />
          )}
          {enabled("mg") && <MgSection value={value} update={update} sources={sources} items={workItems} />}
        </>
      )}
    </section>
  );
}

type SectionProps = {
  workspaceId: string;
  item: SupplementWorkItem;
  value: SupplementMaterialsValue;
  update: (change: (current: SupplementMaterialsValue) => SupplementMaterialsValue) => void;
  report: (key: string, count: number) => void;
};

function useProjectMaterials(workspaceId: string, projectId: string) {
  const [rows, setRows] = useState<MaterialRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let live = true;
    listMaterials(workspaceId, projectId).then(data => { if (live) { setRows(data); setLoaded(true); } }).catch(() => { if (live) setLoaded(true); });
    return () => { live = false; };
  }, [workspaceId, projectId]);
  return { rows, setRows, loaded };
}

function Thumb({ row }: { row: MaterialRow }) {
  const src = mediaUrl(row.url);
  if (row.kind === "video") {
    return <span className={styles.thumb}><video src={src} muted playsInline preload="metadata" /><em><FileVideo size={11} />视频</em></span>;
  }
  return <span className={styles.thumb}>{src ? <img src={src} alt={row.label} loading="lazy" /> : <ImageIcon size={18} />}</span>;
}

// ---------------------------------------------------------------- 我的素材

function MineSection({ workspaceId, item, value, update, report }: SectionProps) {
  const { rows, setRows } = useProjectMaterials(workspaceId, item.project_id);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const ids = value.items[item.id]?.by_source?.mine ?? [];
  const mine = rows.filter(row => ids.includes(row.id));
  const placement = value.sources.mine?.placement ?? "auto";
  const sentences = useMemo(() => splitSentences(item.script_text), [item.script_text]);
  const pins = value.items[item.id]?.pins ?? {};
  const inFlight = uploads.filter(row => !row.error).length;
  useEffect(() => { report(`mine:${item.id}`, inFlight); }, [inFlight, item.id, report]);
  useEffect(() => () => report(`mine:${item.id}`, 0), [item.id, report]);

  const add = (files: FileList | File[]) => {
    const picked = [...files];
    const bad = picked.filter(file => !MEDIA.test(file.name));
    setError(bad.length ? `${bad.map(file => file.name).join("、")} 不是支持的格式（JPG、PNG、WebP、MP4、MOV、WebM）。` : "");
    for (const file of picked.filter(file => MEDIA.test(file.name))) {
      const id = crypto.randomUUID();
      setUploads(current => [...current, { id, name: file.name, percent: 0 }]);
      uploadMaterial(workspaceId, item.project_id, file, "商家上传的补充素材，放在画面最贴合的句子", progress => {
        const percent = progress.total ? Math.round((progress.loaded / progress.total) * 100) : 0;
        setUploads(current => current.map(row => row.id === id ? { ...row, percent } : row));
      }).then(row => {
        setRows(current => [row, ...current.filter(other => other.id !== row.id)]);
        update(current => setSourceMaterials(current, item.id, "mine", [...(current.items[item.id]?.by_source?.mine ?? []), row.id]));
        setUploads(current => current.filter(other => other.id !== id));
      }).catch(failure => {
        setUploads(current => current.map(row => row.id === id ? { ...row, error: message(failure, "上传失败，请重试。") } : row));
      });
    }
  };
  const setPlacementMode = (mode: "auto" | "manual") => {
    update(current => setPlacement(current, mode));
    if (mode === "auto") for (const row of mine) if (pins[row.id] !== undefined) void placeMaterial(workspaceId, item.project_id, row.id, null).catch(() => undefined);
  };
  const remove = async (row: MaterialRow) => {
    update(current => setSourceMaterials(current, item.id, "mine", (current.items[item.id]?.by_source?.mine ?? []).filter(id => id !== row.id)));
    try { await deleteMaterial(workspaceId, item.project_id, row.id); setRows(current => current.filter(other => other.id !== row.id)); } catch { /* 已被剪辑引用时保留原件，只是不再选用 */ }
  };
  const drop = (event: DragEvent<HTMLLabelElement>) => { event.preventDefault(); setDragging(false); add(event.dataTransfer.files); };
  const pin = async (row: MaterialRow, index: number | null) => {
    try {
      const saved = await placeMaterial(workspaceId, item.project_id, row.id, index === null ? null : { index, text: sentences[index] });
      setRows(current => current.map(other => other.id === saved.id ? saved : other));
      update(current => setPin(current, item.id, row.id, index));
      setError("");
    } catch (failure) {
      setError(message(failure, "没能改放置的句子，请重试。"));
    }
  };

  return (
    <section className={styles.section} aria-label="我的素材">
      <div className={styles.sectionHead}>
        <h4>我的素材</h4>
        <div className={styles.segment} role="radiogroup" aria-label="素材放在哪里">
          {(["auto", "manual"] as const).map(mode => (
            <button key={mode} type="button" role="radio" aria-checked={placement === mode} onClick={() => setPlacementMode(mode)}>
              {mode === "auto" ? "自动放到合适的句子" : "我来指定句子"}
            </button>
          ))}
        </div>
      </div>
      <label className={styles.drop} data-dragging={dragging} onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop}>
        <Upload size={18} />
        <b>选择或拖入图片、视频</b>
        <small>可一次选多个 · 图片 JPG/PNG/WebP · 视频 MP4/MOV/WebM，最长 5 分钟</small>
        <input type="file" multiple accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm" onChange={event => { if (event.target.files) add(event.target.files); event.target.value = ""; }} />
      </label>
      {placement === "manual" && <p className={styles.note}>第 1 句是开场标题，素材从第 2 句开始放。</p>}
      {error && <p className={styles.error}>{error}</p>}
      {uploads.length > 0 && (
        <ul className={styles.uploads}>
          {uploads.map(row => (
            <li key={row.id}>
              <span>{row.name}</span>
              {row.error ? <em className={styles.error}>{row.error}</em> : <progress max={100} value={row.percent} aria-label={`${row.name} 上传进度`} />}
              {row.error && <button type="button" onClick={() => setUploads(current => current.filter(other => other.id !== row.id))}>移除</button>}
            </li>
          ))}
        </ul>
      )}
      {mine.length > 0 ? (
        <ul className={styles.tiles}>
          {mine.map(row => (
            <li key={row.id}>
              <Thumb row={row} />
              <span className={styles.tileName} title={row.label}>{row.label}</span>
              {placement === "manual" && (
                <select
                  aria-label={`${row.label} 放在哪一句`}
                  value={pins[row.id] ?? ""}
                  onChange={event => void pin(row, event.target.value === "" ? null : Number(event.target.value))}
                >
                  <option value="">自动</option>
                  {sentences.map((text, index) => (
                    <option key={index} value={index} disabled={index === 0}>
                      第 {index + 1} 句 · {index === 0 ? "开场标题，不放素材" : text.slice(0, 14)}
                    </option>
                  ))}
                </select>
              )}
              <button type="button" className={styles.iconButton} onClick={() => void remove(row)} aria-label={`删除 ${row.label}`}><Trash2 size={13} /></button>
            </li>
          ))}
        </ul>
      ) : !uploads.length && <p className={styles.empty}>还没有上传素材。</p>}
    </section>
  );
}

// ---------------------------------------------------------------- 网上免费素材

function StockSection({ workspaceId, item, value, update, report, sources }: SectionProps & { sources?: SourcesResponse }) {
  const { rows, setRows } = useProjectMaterials(workspaceId, item.project_id);
  const [result, setResult] = useState<StockSearchResponse>();
  const [searching, setSearching] = useState(false);
  const [importing, setImporting] = useState<Record<number, string>>({});
  const [error, setError] = useState("");
  const stockIds = value.items[item.id]?.by_source?.stock;
  const chosen = useMemo(() => stockIds ?? [], [stockIds]);
  const bySentence = useMemo(() => {
    const map = new Map<number, MaterialRow>();
    for (const row of rows) {
      const index = row.provenance?.sentence_index;
      if (chosen.includes(row.id) && typeof index === "number") map.set(index, row);
    }
    return map;
  }, [rows, chosen]);
  const rowsRef = useRef(rows);
  const bySentenceRef = useRef(bySentence);
  useEffect(() => { rowsRef.current = rows; bySentenceRef.current = bySentence; }, [rows, bySentence]);
  const busy = Object.keys(importing).length + (searching ? 1 : 0);
  useEffect(() => { report(`stock:${item.id}`, busy); }, [busy, item.id, report]);
  useEffect(() => () => report(`stock:${item.id}`, 0), [item.id, report]);

  const choose = useCallback(async (sentence: { index: number; text: string }, token: string) => {
    setImporting(current => ({ ...current, [sentence.index]: token }));
    try {
      const row = await importStock(workspaceId, {
        project_id: item.project_id, request_id: crypto.randomUUID(), token,
        sentence_index: sentence.index, sentence: sentence.text, work_item_ref: item.id,
      });
      setRows(current => [row, ...current.filter(other => other.id !== row.id)]);
      update(current => {
        const keep = (current.items[item.id]?.by_source?.stock ?? []).filter(id => {
          const other = rowsRef.current.find(r => r.id === id);
          return other?.provenance?.sentence_index !== sentence.index;
        });
        return setSourceMaterials(current, item.id, "stock", [...keep, row.id]);
      });
    } catch (failure) {
      setError(message(failure, "这个素材没下载成功，换一个试试。"));
    } finally {
      setImporting(current => { const next = { ...current }; delete next[sentence.index]; return next; });
    }
  }, [workspaceId, item.id, item.project_id, setRows, update]);

  const pinned = useMemo(() => Object.values(value.items[item.id]?.pins ?? {}), [value.items, item.id]);
  const search = useCallback(async () => {
    setSearching(true); setError("");
    try {
      // 每句最多一个补充素材：我指定过的句子不再找免费素材。
      const data = await searchStock(workspaceId, item.script_text, undefined, pinned);
      setResult(data);
      if (!data.providers.length) setError("免费素材库暂时无法访问，可以先用其他方式补充。");
      // 默认自动挑每句最合适的一个（已经选过的不动）。
      for (const sentence of data.sentences) {
        const first = sentence.candidates[0];
        if (first && !bySentenceRef.current.has(sentence.index)) void choose(sentence, first.token);
      }
    } catch (failure) {
      setError(message(failure, "暂时搜不到素材，稍后再试。"));
    } finally {
      setSearching(false);
    }
  }, [workspaceId, item.script_text, choose, pinned]);
  const started = useRef(false);
  useEffect(() => {
    if (started.current || !item.script_text.trim()) return;
    started.current = true;
    void search();
  }, [item.script_text, search]);

  const drop = (index: number) => {
    const row = bySentence.get(index);
    if (row) update(current => setSourceMaterials(current, item.id, "stock", (current.items[item.id]?.by_source?.stock ?? []).filter(id => id !== row.id)));
  };
  const providers = sources?.stock_providers ?? [];

  return (
    <section className={styles.section} aria-label="网上免费素材">
      <div className={styles.sectionHead}>
        <h4>网上免费素材</h4>
        <button type="button" className={styles.textButton} onClick={() => void search()} disabled={searching}>
          <RefreshCw size={13} />{searching ? "正在按口播稿找…" : "重新找一遍"}
        </button>
      </div>
      <p className={styles.note}>
        {providers.map(row => `${row.label}${row.available ? "" : `（${row.reason ?? "暂未开通"}）`}`).join(" · ")}
        。素材下载到我们自己的服务器再使用，每个都记录来源和授权。
      </p>
      {error && <p className={styles.error}>{error}</p>}
      {!item.script_text.trim() && <p className={styles.empty}>这条视频没有口播稿，暂时无法按句找素材。</p>}
      {result && (
        <ol className={styles.sentences}>
          {result.sentences.map(sentence => {
            const picked = bySentence.get(sentence.index);
            return (
              <li key={sentence.index}>
                <p className={styles.sentence}><span>第 {sentence.index + 1} 句</span>{sentence.text}</p>
                {sentence.candidates.length ? (
                  <div className={styles.candidates}>
                    {sentence.candidates.map(candidate => {
                      const isPicked = picked?.provenance?.page_url === candidate.page_url;
                      return (
                        <button
                          key={candidate.token}
                          type="button"
                          className={styles.candidate}
                          aria-pressed={isPicked}
                          disabled={Boolean(importing[sentence.index])}
                          onClick={() => void choose(sentence, candidate.token)}
                          title={`${candidate.provider_label} · ${candidate.author} · ${candidate.license}`}
                        >
                          <img src={mediaUrl(stockThumbUrl(workspaceId, candidate.token))} alt="" loading="lazy" />
                          {candidate.kind === "video" && <em><FileVideo size={10} />{Math.round((candidate.duration_ms ?? 0) / 1000)}秒</em>}
                          {importing[sentence.index] === candidate.token && <i>下载中…</i>}
                        </button>
                      );
                    })}
                    {picked && <button type="button" className={styles.textButton} onClick={() => drop(sentence.index)}>这句不用</button>}
                  </div>
                ) : <p className={styles.empty}>没找到合适的素材，这句不配。</p>}
                {picked && (
                  <p className={styles.licence}>
                    {licenceLine(picked.provenance)}
                    {typeof picked.provenance?.page_url === "string" && <a href={picked.provenance.page_url} target="_blank" rel="noreferrer noopener">查看原图</a>}
                  </p>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- AI 生成素材

function AiSection({ workspaceId, item, value, update, report }: SectionProps) {
  const { rows: materials, setRows: setMaterials } = useProjectMaterials(workspaceId, item.project_id);
  const max = value.sources.ai_image?.max_images ?? 4;
  const [estimate, setEstimate] = useState<AiEstimateResponse>();
  const [skip, setSkip] = useState<number[]>([]);
  const [rows, setRows] = useState<AiImageRow[]>([]);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);
  const aiIds = value.items[item.id]?.by_source?.ai_image;
  const chosen = useMemo(() => aiIds ?? [], [aiIds]);
  const running = rows.filter(row => row.status === "queued" || row.status === "running");
  useEffect(() => { report(`ai:${item.id}`, running.length + (confirming ? 1 : 0)); }, [running.length, confirming, item.id, report]);
  useEffect(() => () => report(`ai:${item.id}`, 0), [item.id, report]);

  // 刷新后恢复：已选的 AI 配图从素材列表里找回来（不在本次会话 rows 里的）。
  const shown = useMemo(() => {
    const restored: AiImageRow[] = materials
      .filter(row => row.origin === "ai_generated" && chosen.includes(row.id) && !rows.some(other => other.material_id === row.id))
      .map(row => ({
        id: String(row.provenance?.image_request_id ?? row.id), request_id: "", work_item_ref: item.id,
        sentence_index: Number(row.provenance?.sentence_index ?? 0), sentence: row.description, subject: "",
        status: "succeeded", reused: false, material_id: row.id, error: null, material: row,
      }));
    return [...restored, ...rows];
  }, [materials, chosen, rows, item.id]);

  const stockPicks = value.items[item.id]?.by_source?.stock;
  const pinsMap = value.items[item.id]?.pins;
  const covered = useMemo(() => {
    const fromStock = materials
      .filter(row => stockPicks?.includes(row.id) && typeof row.provenance?.sentence_index === "number")
      .map(row => row.provenance?.sentence_index as number);
    return [...new Set([...fromStock, ...Object.values(pinsMap ?? {})])].sort((a, b) => a - b);
  }, [materials, stockPicks, pinsMap]);
  const coveredKey = covered.join(",");
  useEffect(() => {
    if (!item.script_text.trim()) return;
    let live = true;
    // 已有我的素材 / 免费素材的句子不再配 AI 图。
    estimateAiImages(workspaceId, item.script_text, max, coveredKey ? coveredKey.split(",").map(Number) : [])
      .then(data => { if (live) setEstimate(data); })
      .catch(failure => { if (live) setError(message(failure, "暂时无法估算配图张数。")); });
    return () => { live = false; };
  }, [workspaceId, item.script_text, max, coveredKey]);

  useEffect(() => {
    if (!running.length) return;
    const timer = window.setInterval(() => {
      aiImageStatus(workspaceId, item.project_id, running.map(row => row.id)).then(fresh => {
        setRows(current => current.map(row => fresh.find(other => other.id === row.id) ?? row));
        const done = fresh.filter(row => row.status === "succeeded" && row.material);
        if (done.length) {
          setMaterials(current => [...done.map(row => row.material as MaterialRow), ...current.filter(other => !done.some(row => row.material?.id === other.id))]);
          update(current => setSourceMaterials(current, item.id, "ai_image", [...(current.items[item.id]?.by_source?.ai_image ?? []), ...done.map(row => row.material_id as string)]));
        }
      }).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [running, workspaceId, item.project_id, item.id, update, setMaterials]);

  const plan = (estimate?.items ?? []).filter(row => !skip.includes(row.sentence_index) && !shown.some(other => other.sentence_index === row.sentence_index && other.status !== "failed"));
  const generate = async () => {
    if (!plan.length) return;
    setConfirming(true); setError("");
    try {
      const created = await createAiImages(workspaceId, {
        project_id: item.project_id, work_item_ref: item.id,
        items: plan.map(row => ({ request_id: crypto.randomUUID(), sentence_index: row.sentence_index, sentence: row.sentence, subject: row.subject, purpose: row.purpose })),
      });
      setRows(current => [...current, ...created]);
      const reused = created.filter(row => row.status === "succeeded" && row.material_id);
      if (reused.length) {
        update(current => setSourceMaterials(current, item.id, "ai_image", [...(current.items[item.id]?.by_source?.ai_image ?? []), ...reused.map(row => row.material_id as string)]));
        aiImageStatus(workspaceId, item.project_id, reused.map(row => row.id)).then(fresh => setRows(current => current.map(row => fresh.find(other => other.id === row.id) ?? row))).catch(() => undefined);
      }
    } catch (failure) {
      setError(message(failure, "没能开始生成，未扣积分，请稍后再试。"));
    } finally {
      setConfirming(false);
    }
  };
  const regenerate = async (row: AiImageRow) => {
    try {
      const fresh = await regenerateAiImage(workspaceId, row.id, crypto.randomUUID());
      update(current => setSourceMaterials(current, item.id, "ai_image", (current.items[item.id]?.by_source?.ai_image ?? []).filter(id => id !== row.material_id)));
      setRows(current => [...current.filter(other => other.id !== row.id), fresh]);
    } catch (failure) {
      setError(message(failure, "没能重新生成，未扣积分。"));
    }
  };
  const remove = (row: AiImageRow) => {
    update(current => setSourceMaterials(current, item.id, "ai_image", (current.items[item.id]?.by_source?.ai_image ?? []).filter(id => id !== row.material_id)));
    setRows(current => current.filter(other => other.id !== row.id));
  };
  const credits = estimate?.credits_per_image;

  return (
    <section className={styles.section} aria-label="AI 生成素材">
      <div className={styles.sectionHead}>
        <h4>AI 生成素材</h4>
        <span className={styles.note}>{credits ? `${credits} 积分/张 · 失败不扣` : "按实际张数计费"}</span>
      </div>
      {error && <p className={styles.error}>{error}</p>}
      {!item.script_text.trim() && <p className={styles.empty}>这条视频没有口播稿，暂时无法按句配图。</p>}
      {estimate && estimate.items.length === 0 && <p className={styles.empty}>这条稿子里没有适合画成配图的句子（态度句、口号不配图）。</p>}
      {plan.length > 0 && (
        <div className={styles.confirm}>
          <ol>
            {plan.map(row => (
              <li key={row.sentence_index}>
                <span>第 {row.sentence_index + 1} 句</span>
                <p>{row.sentence}<small>画面：{row.subject}</small></p>
                <button type="button" className={styles.textButton} onClick={() => setSkip(current => [...current, row.sentence_index])}>不配</button>
              </li>
            ))}
          </ol>
          <div className={styles.confirmBar}>
            <span>将生成 {aiCost(plan.length, credits)}，按实际生成成功的张数扣，失败不扣。</span>
            <button type="button" className={styles.primary} disabled={confirming} onClick={() => void generate()}>
              {confirming ? "正在提交…" : `确认生成${credits ? `（${plan.length * credits} 积分）` : ""}`}
            </button>
          </div>
        </div>
      )}
      {shown.length > 0 && (
        <ul className={styles.tiles}>
          {shown.map(row => {
            const material = row.material ?? materials.find(other => other.id === row.material_id);
            const picked = Boolean(row.material_id && chosen.includes(row.material_id));
            return (
              <li key={row.id} data-status={row.status}>
                {material ? <Thumb row={material} /> : <span className={styles.thumb}><i>{row.status === "failed" ? "未生成" : "生成中…"}</i></span>}
                <span className={styles.tileName}>第 {row.sentence_index + 1} 句{row.reused ? " · 复用，未扣积分" : ""}</span>
                {row.status === "failed" && <small className={styles.error}>{row.error}</small>}
                <span className={styles.tileActions}>
                  {(row.status === "succeeded" || row.status === "failed") && (
                    <button type="button" className={styles.textButton} onClick={() => void regenerate(row)} title={credits ? `重新生成一张，${credits} 积分` : "重新生成一张"}>
                      <RefreshCw size={12} />重新生成{credits ? ` · ${credits} 积分` : ""}
                    </button>
                  )}
                  {picked && <button type="button" className={styles.iconButton} onClick={() => remove(row)} aria-label="不用这张"><Trash2 size={13} /></button>}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- MG 动效

// MG 品牌色（与后端 app/mg/catalog.py STYLES 一致；不随站点主题换算，无蓝紫）。
const MG_COLOURS: Record<SupplementStyle, Record<string, string>> = {
  paper: { "--mg-bg": "#F4F0E9", "--mg-fg": "#151311", "--mg-accent": "#D9572B", "--mg-sub": "#8C857C" },
  ink: { "--mg-bg": "#151311", "--mg-fg": "#F4F0E9", "--mg-accent": "#E9893A", "--mg-sub": "#B8955A" },
  ember: { "--mg-bg": "#D9572B", "--mg-fg": "#F4F0E9", "--mg-accent": "#151311", "--mg-sub": "#F4F0E9" },
};

const PREVIEWS = [
  { key: "data_callout", label: "数据强调", body: <><strong>72</strong><em>小时</em><small>持久保湿</small></> },
  { key: "checklist", label: "要点清单", body: <><small>✓ 无酒精</small><small>✓ 无香精</small><small>✓ 孕妇可用</small></> },
  { key: "compare_split", label: "对比卡", body: <><small>以前<br /><b>涂三层</b></small><i /><small>现在<br /><b>一瓶搞定</b></small></> },
  { key: "quote_card", label: "金句", body: <><strong>“</strong><small>好皮肤是养出来的</small></> },
];

function MgSection({ value, update, sources, items }: { value: SupplementMaterialsValue; update: SectionProps["update"]; sources?: SourcesResponse; items: SupplementWorkItem[] }) {
  const style = value.sources.mg?.style ?? "paper";
  const unsupported = items.filter(item => item.supports_mg === false).length;
  return (
    <section className={styles.section} aria-label="MG 动效">
      <div className={styles.sectionHead}>
        <h4>MG 动效</h4>
        <span className={styles.note}>没有素材的段落用动效补；全屏动效每段不超过 2.5 秒</span>
      </div>
      {items.length > 1 && <p className={styles.note}>MG 动效按整批设置：本批全部 {items.length} 条视频都会使用，风格相同。</p>}
      {unsupported > 0 && <p className={styles.note}>{unsupported} 条视频用的模板不支持 MG 动效，这几条不会加。</p>}
      <div className={styles.segment} role="radiogroup" aria-label="动效风格">
        {(sources?.mg_styles.map(row => row.key) ?? (["paper", "ink", "ember"] as SupplementStyle[])).map(key => (
          <button key={key} type="button" role="radio" aria-checked={style === key} onClick={() => update(current => setMgStyle(current, key))}>
            <span className={styles.swatch} style={MG_COLOURS[key] as CSSProperties} aria-hidden />{STYLE_COPY[key]}
          </button>
        ))}
      </div>
      <ul className={styles.mgPreview} style={MG_COLOURS[style] as CSSProperties}>
        {PREVIEWS.map(row => (
          <li key={row.key}>
            <div className={styles.mgFrame}><div className={styles.mgCard} data-kind={row.key}>{row.body}</div></div>
            <span>{row.label}</span>
          </li>
        ))}
      </ul>
      <p className={styles.note}>动效上的文字都取自这条视频里实际说出的话，不改写、不编造。</p>
    </section>
  );
}
