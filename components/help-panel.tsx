import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Lightbulb,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

export function HelpPanel({
  mode,
}: {
  mode: "local-edit" | "detail-pack";
}) {
  const local = mode === "local-edit";
  const steps = local
    ? ["上传清晰原图", "绘制并确认授权选区", "描述期望变化", "验证并下载锁定结果"]
    : ["上传同一商品多角度图", "完善卖点与渠道信息", "确认页面规划", "逐页生成并检查结果"];

  return (
    <aside className="help-panel">
      <div className="help-panel__title">
        <span>
          <BookOpen size={17} />
        </span>
        <div>
          <strong>创作助手</strong>
          <p>跟随步骤，高效得到好结果</p>
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
          <span>{local ? "交付质量" : "输出规格"}</span>
          <b>{local ? "最终质量" : "天猫 · 中文 · 6页"}</b>
        </div>
      </section>
      <section className="help-card">
        <div className="help-card__head">
          <span>操作路径</span>
          <em>{local ? "约 2 分钟" : "约 8 分钟"}</em>
        </div>
        <ol className="help-steps">
          {steps.map((step, index) => (
            <li key={step} className={index < 2 ? "done" : index === 2 ? "current" : ""}>
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
              ? "选区比目标多覆盖 8–16px，有助于自然融合；最终交付仍只修改授权区域。"
              : "使用相同光线与焦段的多角度照片，可提升商品结构识别与跨页一致性。"}
          </p>
        </div>
      </section>
      <section className="help-card safety-card">
        <div className="help-card__icon">
          {local ? <ShieldCheck size={17} /> : <Sparkles size={17} />}
        </div>
        <div>
          <strong>{local ? "像素锁定保障" : "断点生成保障"}</strong>
          <p>
            {local
              ? "原图是唯一画布，选区外像素将经过严格比对，不合格结果不会覆盖原始产物。"
              : "已完成页面会被保留。遇到失败时，只重试缺失页面，不重复消耗成功结果。"}
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
            : "规划未通过结构校验前，不会进入图片生成。"}
        </p>
      </div>
    </aside>
  );
}

