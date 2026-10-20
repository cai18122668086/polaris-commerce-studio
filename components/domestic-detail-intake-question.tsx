"use client";

import { useEffect, useRef, useState } from "react";
import { AlertCircle, ArrowRight, ImagePlus, LoaderCircle, X } from "lucide-react";
import { useUploadAsset } from "@/features/assets/api/assets";
import { useResolveDetailIntake } from "@/features/jobs/api/jobs";
import { errorMessage } from "@/lib/api/request";
import type { JobDetail } from "@/lib/api/types";
import { IMAGE_UPLOAD_ACCEPT } from "@/lib/image-upload";

export const BRANDLESS_CONFIRMATION = "我确认当前商品无品牌，全部详情图不添加独立品牌标志。";
const object = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const objects = (value: unknown): Record<string, unknown>[] => Array.isArray(value) ? value.map(object) : [];

export function DomesticDetailIntakeQuestion({ workspaceId, job }: { workspaceId?: string; job: JobDetail }) {
  const resolve = useResolveDetailIntake(workspaceId);
  const upload = useUploadAsset(workspaceId);
  const fileInput = useRef<HTMLInputElement>(null);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [brandless, setBrandless] = useState(false);
  const [extraImages, setExtraImages] = useState<{ id: string; preview: string }[]>([]);
  const [uploadError, setUploadError] = useState<string>();
  const imagesRef = useRef(extraImages);
  useEffect(() => { imagesRef.current = extraImages; }, [extraImages]);
  useEffect(() => () => imagesRef.current.forEach(image => URL.revokeObjectURL(image.preview)), []);
  const intake = object(job.plan?.payload.product_intake);
  const conflicts = objects(intake.source_conflicts);
  const facts = [...objects(intake.user_facts), ...objects(intake.observed_facts)];
  const factById = new Map(facts.map(fact => [String(fact.id), fact]));
  const needsBrand = intake.brand_confirmation_required === true;
  const allSelected = conflicts.every(conflict => Array.isArray(conflict.alternative_fact_ids) && conflict.alternative_fact_ids.includes(choices[String(conflict.id)]));
  const canSubmit = allSelected && (!needsBrand || brandless || extraImages.length > 0);

  async function addImages(files: File[]) {
    setUploadError(undefined);
    for (const file of files.slice(0, 2 - extraImages.length)) {
      const preview = URL.createObjectURL(file);
      try {
        const asset = await upload.mutateAsync({ file, mediaKind: "image" });
        setExtraImages(current => [...current, { id: asset.id, preview }]);
      } catch (error) { URL.revokeObjectURL(preview); setUploadError(errorMessage(error)); }
    }
  }

  function submit() {
    if (!canSubmit || !job.plan) return;
    resolve.mutate({ jobId: job.id, allowedActions: job.allowed_actions, revision: job.plan.revision,
      confirmationText: "我确认以上事实取舍，按选定的商品规格和品牌信息继续分析。",
      resolutions: conflicts.map(conflict => {
        const id = String(conflict.id); const alternatives = conflict.alternative_fact_ids as string[];
        return { conflict_id: id, retained_fact_ids: [choices[id]], rejected_fact_ids: alternatives.filter(value => value !== choices[id]) };
      }), brandlessConfirmation: brandless ? BRANDLESS_CONFIRMATION : undefined,
      additionalProductAssetIds: brandless ? [] : extraImages.map(image => image.id) });
  }

  return <section className="detail-form-card" aria-label="商品事实确认">
    <div className="form-section-head"><AlertCircle size={22} /><div><h2>先确认商品信息</h2><p>确认以下内容后，将继续分析同一任务，再提供完整详情规划供您审阅。</p></div></div>
    {conflicts.map(conflict => <fieldset key={String(conflict.id)} className="detail-form-card">
      <legend>{String(conflict.topic)}</legend><p>{String(conflict.why_material)}</p>
      {(conflict.alternative_fact_ids as string[]).map(id => {
        const fact = factById.get(id);
        return <label key={id} style={{ display: "block", marginBlock: 10 }}><input type="radio" name={`source-${String(conflict.id)}`} checked={choices[String(conflict.id)] === id}
          onChange={() => setChoices(current => ({ ...current, [String(conflict.id)]: id }))} /><strong>{String(fact?.text ?? id)}</strong>
          <small style={{ display: "block", marginLeft: 24 }}>{fact?.source_class === "USER_FACT" ? "您填写的商品事实" : `商品图观察 · ${String(fact?.observed_region ?? "可见区域")}`}</small></label>;
      })}
    </fieldset>)}
    {needsBrand && <div className="form-grid">
      <p className="full">现有图片尚未提供可用的清晰品牌标识。请确认无品牌，或补充清晰的本商品品牌图片。</p>
      <label className="full"><span><input style={{ width: "auto", marginRight: 8 }} type="checkbox" checked={brandless} onChange={event => setBrandless(event.target.checked)} />{BRANDLESS_CONFIRMATION}</span></label>
      {!brandless && <div className="full multi-uploader">
        {extraImages.map(image => <div key={image.id} className="upload-thumb"><img src={image.preview} alt="补充品牌商品图" /><button aria-label="移除补充图片" onClick={() => {
          URL.revokeObjectURL(image.preview); setExtraImages(current => current.filter(value => value.id !== image.id));
        }}><X size={13} /></button></div>)}
        {extraImages.length < 2 && <button className="upload-more" disabled={upload.isPending} onClick={() => fileInput.current?.click()}><ImagePlus size={22} />补充品牌商品图</button>}
        <input ref={fileInput} type="file" className="visually-hidden" multiple accept={IMAGE_UPLOAD_ACCEPT} onChange={event => {
          const files = Array.from(event.currentTarget.files ?? []); event.currentTarget.value = ""; void addImages(files);
        }} />
      </div>}
    </div>}
    {(resolve.error || uploadError) && <div className="api-state api-state--error" role="alert"><p>{uploadError ?? errorMessage(resolve.error)}</p></div>}
    <p>提交即确认以上事实取舍；此步骤只继续分析，不授权生图。</p>
    <button className="primary-button" onClick={submit} disabled={!canSubmit || resolve.isPending || upload.isPending}>{resolve.isPending ? <LoaderCircle className="spin" size={17} /> : <ArrowRight size={17} />}确认商品信息并继续分析</button>
  </section>;
}
