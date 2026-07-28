"use client";

import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Lightbulb,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import {
  presentWorkflow,
  useRuntimeStatus,
} from "@/features/runtime/api/runtime";

export function HelpPanel({
  mode,
}: {
  mode: "local-edit" | "detail-pack";
}) {
  const local = mode === "local-edit";
  const runtime = useRuntimeStatus();
  const workflow = presentWorkflow(
    local
      ? runtime.data?.capabilities.local_edit
      : runtime.data?.capabilities.detail_pack,
  );
  const providerEnabled = workflow.canDeliverImages;
  const mockEnabled = workflow.mode === "mock";
  const steps = local
    ? [
        "上传清晰原图",
        "绘制并确认授权选区",
        "描述期望变化",
        providerEnabled
          ? "验证并下载 Provider 锁定结果"
          : mockEnabled
            ? "验证模拟任务状态；真实生成接入后才可下载"
            : "等待能力状态恢复；真实生成当前未启用",
      ]
    : [
        "上传同一商品多角度图",
        "完善卖点与渠道信息",
        "确认页面规划",
        providerEnabled
          ? "逐页生成并检查 Provider 结果"
          : mockEnabled
            ? "检查模拟流程终态；当前无图片产物"
            : "等待能力状态恢复；当前不进入图片生成",
      ];

  return (
    <aside className="help-panel">
      <div className="help-panel__title">
        <span>
          <BookOpen size={17} />
        </span>
        <div>
          <strong>创作助手</strong>
          <p>
            {providerEnabled
              ? "跟随步骤检查真实结果"
              : mockEnabled
                ? "当前仅验证内部模拟流程"
                : "能力状态未知，按未启用处理"}
          </p>
        </div>
      </div>
      <section className="help-card current-summary">
        <div className="help-card__head">
          <span>当前任务</span>
          <em>已自动保存</em>
        </div>
        <strong>{local ? "耳机材质精修" : "LUMIÈRE 精华液详情套图"}</strong>
        <div className="summary-row">
          <span>{local ? "编辑画布" : "商品素材"}</span>
          <b>{local ? "1 张 · 已选区" : "4 张 · 同一分组"}</b>
        </div>
        <div className="summary-row">
          <span>{local ? "运行模式" : "输出规格"}</span>
          <b>
            {local
              ? providerEnabled
                ? "Provider 交付"
                : mockEnabled
                  ? "mock · 无图片产物"
                  : "能力未知 · 无图片产物"
              : "天猫 · 中文 · 6页"}
          </b>
        </div>
      </section>
      <section className="help-card">
        <div className="help-card__head">
          <span>操作路径</span>
          <em>{local ? "约 2 分钟" : "约 8 分钟"}</em>
        </div>
        <ol className="help-steps">
          {steps.map((step, index) => (
            <li
              key={step}
              className={index < 2 ? "done" : index === 2 ? "current" : ""}
            >
              <i>{index < 2 ? <CheckCircle2 size={15} /> : index + 1}</i>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      </section>
      <section className="help-card suggestion-card">
        <div className="help-card__icon">
          <Lightbulb size={17} />
        </div>
        <div>
          <strong>{local ? "选区边缘建议" : "素材一致性建议"}</strong>
          <p>
            {local
              ? providerEnabled
                ? "选区比目标多覆盖 8–16px，有助于自然融合；Provider 交付仍只修改授权区域。"
                : mockEnabled
                  ? "选区会作为模拟任务的授权边界保存；当前不会生成或交付修改图片。"
                  : "能力状态未知；选区可继续编辑，但当前不会提交图片生成。"
              : "使用相同光线与焦段的多角度照片，可提升商品结构识别与跨页一致性。"}
          </p>
        </div>
      </section>
      <section className="help-card safety-card">
        <div className="help-card__icon">
          {local ? <ShieldCheck size={17} /> : <Sparkles size={17} />}
        </div>
        <div>
          <strong>{local ? "授权边界状态" : "流程恢复"}</strong>
          <p>
            {local
              ? providerEnabled
                ? "原图是唯一画布，选区外像素将经过严格比对，不合格结果不会覆盖原始产物。"
                : mockEnabled
                  ? "本轮只验证原图、蒙版与任务状态；真实像素锁定结果尚不可下载。"
                  : "能力状态未知，按 fail-closed 处理；不会生成或提供下载结果。"
              : providerEnabled
                ? "已完成页面会被保留。遇到失败时，只重试缺失页面。"
                : mockEnabled
                  ? "模拟任务会保留已完成状态；终态不包含可交付图片。"
                  : "能力状态未知，按 fail-closed 处理；不会进入图片生成。"}
          </p>
        </div>
      </section>
      <button className="help-more">
        查看完整使用指南
        <ChevronRight size={16} />
      </button>
      <div className="risk-note">
        <AlertTriangle size={15} />
        <p>
          {local
            ? "复杂透明边缘建议使用更高质量档位。"
            : providerEnabled
              ? "规划未通过结构校验前，不会进入图片生成。"
              : mockEnabled
                ? "规划确认只推进模拟状态，不会进入真实图片生成。"
                : "能力状态未知，规划确认入口保持关闭。"}
        </p>
      </div>
    </aside>
  );
}
