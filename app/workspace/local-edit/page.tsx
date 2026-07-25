"use client";

import { useEffect, useState } from "react";
import {
  AlertCircle,
  Brush,
  Check,
  CheckCircle2,
  Circle,
  Columns2,
  Download,
  Eraser,
  Expand,
  ImagePlus,
  Info,
  Layers3,
  LoaderCircle,
  MousePointer2,
  Redo2,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  SquareDashed,
  Undo2,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { HelpPanel } from "@/components/help-panel";
import { WorkspaceHeader } from "@/components/workspace-header";
import { productImages } from "@/lib/mock-data";

const qualities = [
  { key: "preview", label: "快速预览", desc: "约 20 秒", cost: "1 次" },
  { key: "balanced", label: "均衡", desc: "约 50 秒", cost: "2 次" },
  { key: "final", label: "最终质量", desc: "约 90 秒", cost: "4 次" },
];

const defaultPrompt =
  "将耳罩外侧的亮面塑料改为细腻的深灰色磨砂金属，保留原有高光方向、品牌标识和结构接缝。";

const promptSuggestions = [
  { label: "保留光影", text: "保留原有光影方向与明暗关系。" },
  { label: "保留结构", text: "保留商品结构、接缝与品牌标识。" },
  { label: "自然融合", text: "让修改边缘与周围材质自然融合。" },
];

type GenerationState = "idle" | "queued" | "processing" | "completed";

export default function LocalEditPage() {
  const [quality, setQuality] = useState("final");
  const [tool, setTool] = useState("brush");
  const [brushSize, setBrushSize] = useState(32);
  const [zoom, setZoom] = useState(72);
  const [selectionStage, setSelectionStage] = useState(2);
  const [prompt, setPrompt] = useState(defaultPrompt);
  const [generationState, setGenerationState] = useState<GenerationState>("idle");
  const [progress, setProgress] = useState(0);
  const [validationMessage, setValidationMessage] = useState("");

  const selectedQuality =
    qualities.find((item) => item.key === quality) ?? qualities[2];
  const selectionPercent = selectionStage === 2 ? 12.4 : selectionStage === 1 ? 6.1 : 0;
  const isGenerating = generationState === "queued" || generationState === "processing";
  const currentStep =
    generationState === "completed" ? 4 : isGenerating ? 3 : selectionStage === 0 ? 1 : 2;

  useEffect(() => {
    if (generationState === "queued") {
      const timer = window.setTimeout(() => {
        setGenerationState("processing");
        setProgress(28);
      }, 700);
      return () => window.clearTimeout(timer);
    }

    if (generationState === "processing") {
      const timer = window.setTimeout(() => {
        const nextProgress = Math.min(progress + 18, 100);
        setProgress(nextProgress);
        if (nextProgress === 100) {
          setGenerationState("completed");
        }
      }, 420);
      return () => window.clearTimeout(timer);
    }
  }, [generationState, progress]);

  const updateSelection = (nextStage: number) => {
    setSelectionStage(Math.max(0, Math.min(2, nextStage)));
    setValidationMessage("");
    if (generationState === "completed") {
      setGenerationState("idle");
      setProgress(0);
    }
  };

  const editSelectionFromCanvas = () => {
    if (tool === "brush" || tool === "rectangle") {
      updateSelection(selectionStage + 1);
    } else if (tool === "eraser") {
      updateSelection(selectionStage - 1);
    }
  };

  const applyPromptSuggestion = (suggestion: (typeof promptSuggestions)[number]) => {
    if (prompt.includes(suggestion.text)) return;
    setPrompt((current) => `${current.trim()}${current.trim() ? "\n" : ""}${suggestion.text}`);
    setValidationMessage("");
  };

  const startGeneration = () => {
    if (selectionStage === 0) {
      setValidationMessage("请先在画布上绘制并确认修改选区。");
      return;
    }
    if (!prompt.trim()) {
      setValidationMessage("请填写选区内需要发生的变化。");
      return;
    }

    setValidationMessage("");
    setGenerationState("queued");
    setProgress(12);
  };

  return (
    <AppShell flush>
      <div className="workspace-page">
        <div className="workspace-main">
          <WorkspaceHeader
            eyebrow="商品图工具"
            title="局部修改"
            description="只改变授权选区，让商品主体、构图与选区外像素保持原样。"
            meta={
              <span className="autosave-state">
                <CheckCircle2 size={15} />
                草稿已保存
              </span>
            }
          />

          <div className="workflow-steps">
            {["上传原图", "绘制选区", "描述修改", "生成与验证"].map((step, index) => (
              <div
                key={step}
                className={index < currentStep ? "done" : index === currentStep ? "active" : ""}
              >
                <i>{index < currentStep ? <Check size={14} /> : index + 1}</i>
                <span>{step}</span>
                {index < 3 && <em />}
              </div>
            ))}
          </div>

          <div className="local-edit-layout">
            <section className="editor-card">
              <div className="card-toolbar">
                <div className="toolbar-group">
                  <button
                    className={tool === "pointer" ? "active" : ""}
                    onClick={() => setTool("pointer")}
                    aria-label="选择工具"
                  >
                    <MousePointer2 size={17} />
                  </button>
                  <button
                    className={tool === "brush" ? "active" : ""}
                    onClick={() => setTool("brush")}
                    aria-label="画笔工具"
                  >
                    <Brush size={17} />
                  </button>
                  <button
                    className={tool === "rectangle" ? "active" : ""}
                    onClick={() => setTool("rectangle")}
                    aria-label="矩形选区"
                  >
                    <SquareDashed size={17} />
                  </button>
                  <button
                    className={tool === "eraser" ? "active" : ""}
                    onClick={() => setTool("eraser")}
                    aria-label="橡皮擦"
                  >
                    <Eraser size={17} />
                  </button>
                </div>
                <div className="brush-control">
                  <span>笔刷</span>
                  <input
                    type="range"
                    min="8"
                    max="80"
                    value={brushSize}
                    onChange={(event) => setBrushSize(Number(event.target.value))}
                    aria-label="笔刷大小"
                  />
                  <b>{brushSize}px</b>
                </div>
                <div className="toolbar-group toolbar-group--right">
                  <button
                    onClick={() => updateSelection(selectionStage - 1)}
                    disabled={selectionStage === 0}
                    aria-label="撤销上一处选区"
                  >
                    <Undo2 size={16} />
                  </button>
                  <button
                    onClick={() => updateSelection(selectionStage + 1)}
                    disabled={selectionStage === 2}
                    aria-label="重做上一处选区"
                  >
                    <Redo2 size={16} />
                  </button>
                  <span />
                  <button
                    onClick={() => setZoom((current) => Math.max(50, current - 10))}
                    disabled={zoom === 50}
                    aria-label="缩小画布"
                  >
                    <ZoomOut size={16} />
                  </button>
                  <b>{zoom}%</b>
                  <button
                    onClick={() => setZoom((current) => Math.min(120, current + 10))}
                    disabled={zoom === 120}
                    aria-label="放大画布"
                  >
                    <ZoomIn size={16} />
                  </button>
                  <button onClick={() => setZoom(72)} aria-label="适应画布">
                    <Expand size={16} />
                  </button>
                </div>
              </div>
              <div className="image-editor">
                <div
                  className={`canvas-frame tool-${tool}`}
                  onClick={editSelectionFromCanvas}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      editSelectionFromCanvas();
                    }
                  }}
                  role="application"
                  tabIndex={0}
                  aria-label="局部修改选区画布。使用画笔或矩形增加选区，使用橡皮擦减少选区。"
                >
                  <div
                    className="canvas-content"
                    style={{ transform: `scale(${zoom / 72})` }}
                  >
                    <img src={productImages.headphones} alt="待修改的黑色头戴耳机" />
                    {selectionStage >= 1 && <div className="mask-shape mask-shape--left" />}
                    {selectionStage >= 2 && <div className="mask-shape mask-shape--right" />}
                    {selectionStage > 0 && (
                      <div className="selection-outline">
                        <span className="selection-label">
                          <Brush size={13} />
                          已授权选区 {selectionPercent}%
                        </span>
                      </div>
                    )}
                  </div>
                </div>
                <div className="canvas-status">
                  <span>
                    <Circle size={9} fill="currentColor" />
                    2048 × 2048 px
                  </span>
                  <span>
                    <Layers3 size={14} />
                    原图画布
                  </span>
                  <span className="safe">
                    <ShieldCheck size={14} />
                    {selectionStage > 0 ? "选区外锁定" : "等待绘制选区"}
                  </span>
                </div>
              </div>
            </section>

            <aside className="edit-controls">
              <section className="control-card">
                <div className="control-card__heading">
                  <span>1</span>
                  <div>
                    <strong>原始图片</strong>
                    <p>PNG · 3.8MB · 2048 × 2048</p>
                  </div>
                  <button aria-label="重新上传">
                    <RotateCcw size={16} />
                  </button>
                </div>
                <div className="uploaded-file">
                  <img src={productImages.headphones} alt="" />
                  <span>
                    <strong>quietform_pro_front.png</strong>
                    <small>图片清晰度良好</small>
                  </span>
                  <CheckCircle2 size={17} />
                </div>
                <button className="link-button">
                  <ImagePlus size={15} />
                  从素材库替换
                </button>
              </section>

              <section className="control-card">
                <div className="control-card__heading">
                  <span>2</span>
                  <div>
                    <strong>修改要求</strong>
                    <p>清楚描述选区内要发生的变化</p>
                  </div>
                </div>
                <div className="textarea-wrap">
                  <textarea
                    value={prompt}
                    maxLength={500}
                    onChange={(event) => {
                      setPrompt(event.target.value);
                      setValidationMessage("");
                    }}
                    aria-label="修改要求"
                  />
                  <span>{prompt.length} / 500</span>
                </div>
                <div className="prompt-chips">
                  {promptSuggestions.map((suggestion) => {
                    const applied = prompt.includes(suggestion.text);
                    return (
                      <button
                        key={suggestion.label}
                        className={applied ? "applied" : ""}
                        onClick={() => applyPromptSuggestion(suggestion)}
                        aria-pressed={applied}
                      >
                        {applied && <Check size={11} />}
                        {suggestion.label}
                      </button>
                    );
                  })}
                </div>
              </section>

              <section className="control-card">
                <div className="control-card__heading">
                  <span>3</span>
                  <div>
                    <strong>生成质量</strong>
                    <p>越高的档位越适合材质与细节</p>
                  </div>
                </div>
                <div className="quality-options">
                  {qualities.map((item) => (
                    <button
                      key={item.key}
                      className={quality === item.key ? "selected" : ""}
                      onClick={() => setQuality(item.key)}
                    >
                      <i>{quality === item.key && <Check size={12} />}</i>
                      <span>
                        <strong>{item.label}</strong>
                        <small>{item.desc}</small>
                      </span>
                      <em>{item.cost}</em>
                    </button>
                  ))}
                </div>
              </section>

              <div className="cost-bar">
                <span>
                  本次预计消耗
                  <Info size={14} />
                </span>
                <strong>{selectedQuality.cost}创作额度</strong>
              </div>
              {(validationMessage || generationState !== "idle") && (
                <div
                  className={`generation-feedback ${
                    validationMessage
                      ? "error"
                      : generationState === "completed"
                        ? "success"
                        : "active"
                  }`}
                  aria-live="polite"
                >
                  <span>
                    {validationMessage ? (
                      <AlertCircle size={16} />
                    ) : generationState === "completed" ? (
                      <CheckCircle2 size={16} />
                    ) : (
                      <LoaderCircle size={16} className="spin" />
                    )}
                  </span>
                  <div>
                    <strong>
                      {validationMessage
                        ? "还不能生成"
                        : generationState === "queued"
                          ? "任务正在排队"
                          : generationState === "processing"
                            ? "正在生成并执行像素锁定"
                            : "严格锁定结果已就绪"}
                    </strong>
                    <p>
                      {validationMessage ||
                        (generationState === "completed"
                          ? "选区外像素校验通过，原始结果与锁定结果均已保留。"
                          : `当前进度 ${progress}% · 请保持此页面打开`)}
                    </p>
                    {!validationMessage && generationState !== "completed" && (
                      <i>
                        <span style={{ width: `${progress}%` }} />
                      </i>
                    )}
                  </div>
                </div>
              )}
              <button
                className="primary-button generate-button"
                onClick={startGeneration}
                disabled={isGenerating}
                aria-busy={isGenerating}
              >
                {isGenerating ? (
                  <LoaderCircle size={17} className="spin" />
                ) : generationState === "completed" ? (
                  <RotateCcw size={17} />
                ) : (
                  <Sparkles size={17} />
                )}
                {generationState === "completed"
                  ? "基于当前设置再次生成"
                  : isGenerating
                    ? "正在处理"
                    : "生成局部修改"}
              </button>
              <p className="privacy-line">
                <ShieldCheck size={13} />
                原图与结果仅用于本次创作，不公开展示
              </p>
            </aside>
          </div>

          <section className="result-preview-card">
            <div className="card-heading">
              <div>
                <span>
                  {generationState === "completed"
                    ? "刚刚完成 · LE-DEMO-0725"
                    : "最近结果 · LE-0725-1638"}
                </span>
                <h2>{generationState === "completed" ? "本次严格锁定结果" : "严格锁定结果"}</h2>
                <p>选区外像素比对通过，原始模型结果与最终交付结果均已保留。</p>
              </div>
              <div className="result-actions">
                <span className="locked-badge">
                  <ShieldCheck size={15} />
                  0 个越界像素
                </span>
                <button className="secondary-button">
                  <Download size={16} />
                  下载 PNG
                </button>
              </div>
            </div>
            <div className="before-after">
              <div>
                <span>原始图片</span>
                <img src={productImages.headphones} alt="修改前耳机" />
              </div>
              <div className="comparison-handle">
                <Columns2 size={17} />
              </div>
              <div className="after-image">
                <span>严格锁定结果</span>
                <img src={productImages.headphones} alt="修改后耳机" />
                <i className="metal-effect" />
              </div>
            </div>
          </section>
        </div>
        <HelpPanel mode="local-edit" />
      </div>
    </AppShell>
  );
}
