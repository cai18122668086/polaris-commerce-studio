"use client";

import { useState } from "react";
import {
  ArrowRight,
  BadgeCheck,
  Boxes,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleDollarSign,
  Clock3,
  FileCheck2,
  Globe2,
  GripVertical,
  ImagePlus,
  Info,
  Languages,
  LoaderCircle,
  MapPin,
  Plus,
  ScanLine,
  Sparkles,
  Store,
  WandSparkles,
  X,
} from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { HelpPanel } from "@/components/help-panel";
import { WorkspaceHeader } from "@/components/workspace-header";
import { detailPages, productImages } from "@/lib/mock-data";
import {
  marketplaceGroups,
  type MarketRegion,
} from "@/lib/marketplaces";

const uploadImages = [
  productImages.skincare,
  productImages.skincare,
  productImages.skincare,
  productImages.skincare,
];

export default function DetailPackPage() {
  const [pageCount, setPageCount] = useState(6);
  const [marketRegion, setMarketRegion] = useState<MarketRegion>("domestic");
  const [marketplaceId, setMarketplaceId] = useState("tmall");
  const [language, setLanguage] = useState<"zh-CN" | "en-US">("zh-CN");
  const selectedMarketplace =
    marketplaceGroups[marketRegion].find((item) => item.id === marketplaceId) ??
    marketplaceGroups[marketRegion][0];

  const selectRegion = (region: MarketRegion) => {
    setMarketRegion(region);
    setMarketplaceId(marketplaceGroups[region][0].id);
    setLanguage(region === "domestic" ? "zh-CN" : "en-US");
  };

  return (
    <AppShell flush>
      <div className="workspace-page">
        <div className="workspace-main">
          <WorkspaceHeader
            eyebrow="电商套图"
            title="商品详情图"
            description="先选择销售地区和电商平台，再按对应规范规划并生成完整商品详情页。"
            meta={
              <span className="autosave-state">
                <CheckCircle2 size={15} />
                草稿已保存
              </span>
            }
          />

          <section className="marketplace-selector">
            <div className="marketplace-selector__head">
              <span className="number-chip">0</span>
              <div>
                <h2>选择目标电商渠道</h2>
                <p>平台不同，图片尺寸、信息结构、语言和审核重点也不同。</p>
              </div>
              <span className="platform-selected-state">
                <CheckCircle2 size={15} />
                已选择 {selectedMarketplace.name}
              </span>
            </div>

            <div className="market-region-switch" aria-label="电商地区">
              <button
                className={marketRegion === "domestic" ? "active" : ""}
                onClick={() => selectRegion("domestic")}
              >
                <MapPin size={17} />
                <span>
                  <strong>国内电商</strong>
                  <small>中国大陆主流电商与内容平台</small>
                </span>
              </button>
              <button
                className={marketRegion === "international" ? "active" : ""}
                onClick={() => selectRegion("international")}
              >
                <Globe2 size={17} />
                <span>
                  <strong>国际电商</strong>
                  <small>跨境平台、独立站与海外市场</small>
                </span>
              </button>
            </div>

            <div className="marketplace-grid">
              {marketplaceGroups[marketRegion].map((marketplace) => (
                <button
                  key={marketplace.id}
                  className={marketplaceId === marketplace.id ? "active" : ""}
                  onClick={() => setMarketplaceId(marketplace.id)}
                >
                  <span className="marketplace-mark">{marketplace.shortName}</span>
                  <span>
                    <strong>{marketplace.name}</strong>
                    <small>{marketplace.format}</small>
                  </span>
                  <i>{marketplaceId === marketplace.id && <Check size={12} />}</i>
                </button>
              ))}
            </div>

            <div className="marketplace-summary">
              <span>
                <Store size={16} />
                推荐出图规格
              </span>
              <strong>{selectedMarketplace.name}</strong>
              <div className="marketplace-specs">
                <span>
                  <small>主图 / Listing</small>
                  <b>{selectedMarketplace.mainImage}</b>
                </span>
                <span>
                  <small>详情 / 内容页</small>
                  <b>{selectedMarketplace.detailImage}</b>
                </span>
              </div>
              <p>
                {selectedMarketplace.note}
                <small>平台规则可能更新，正式发布前请以商家后台为准。</small>
              </p>
            </div>
          </section>

          <div className="workflow-steps detail-steps">
            {["商品素材", "商品信息", "输出设置", "页面规划", "批量生成"].map((step, index) => (
              <div key={step} className={index < 3 ? "done" : index === 3 ? "active" : ""}>
                <i>{index < 3 ? <Check size={14} /> : index + 1}</i>
                <span>{step}</span>
                {index < 4 && <em />}
              </div>
            ))}
          </div>

          <section className="detail-form-card">
            <div className="form-section-head">
              <span className="number-chip">1</span>
              <div>
                <h2>商品素材</h2>
                <p>同一商品的不同角度会进入同一次分析与规划，请勿混入其他商品。</p>
              </div>
              <span className="validation-chip">
                <BadgeCheck size={15} />
                已识别为同一商品
              </span>
            </div>
            <div className="multi-uploader">
              {uploadImages.map((image, index) => (
                <div key={index} className="upload-thumb">
                  <img
                    src={image}
                    alt={`精华液商品角度 ${index + 1}`}
                    style={{
                      objectPosition: `${40 + index * 7}% ${45 + index * 4}%`,
                      transform: `scale(${1 + index * 0.05})`,
                    }}
                  />
                  <span>{["正面", "左侧", "右侧", "包装"][index]}</span>
                  <button aria-label={`移除第 ${index + 1} 张图片`}>
                    <X size={13} />
                  </button>
                  <i>
                    <GripVertical size={14} />
                  </i>
                </div>
              ))}
              <button className="upload-more">
                <ImagePlus size={23} />
                <strong>继续添加</strong>
                <small>最多 8 张</small>
              </button>
            </div>
            <div className="analysis-strip">
              <span>
                <ScanLine size={16} />
                <b>商品一致性 98%</b>
              </span>
              <span>主体：精华液瓶装护肤品</span>
              <span>主色：象牙白 / 鎏金</span>
              <span>图片清晰度：良好</span>
            </div>
          </section>

          <section className="detail-form-card">
            <div className="form-section-head">
              <span className="number-chip">2</span>
              <div>
                <h2>商品信息</h2>
                <p>信息越完整，页面叙事和卖点表达越准确。</p>
              </div>
            </div>
            <div className="form-grid">
              <label>
                <span>商品名称 <i>*</i></span>
                <input defaultValue="LUMIÈRE 鎏金焕亮精华液" />
              </label>
              <label>
                <span>商品品类 <i>*</i></span>
                <div className="select-wrap">
                  <select defaultValue="skincare">
                    <option value="skincare">美容护肤 / 精华</option>
                    <option value="fashion">箱包服饰</option>
                    <option value="electronics">数码家电</option>
                  </select>
                  <ChevronDown size={15} />
                </div>
              </label>
              <label className="full">
                <span>核心卖点 <i>*</i></span>
                <textarea defaultValue="三重焕亮复配，改善暗沉；乳液般轻盈质地，快速吸收不黏腻；45ml 大容量，适合日常维稳与熬夜肌护理。" />
                <small>建议填写 3–5 个真实且可验证的卖点，避免绝对化功效表达。</small>
              </label>
              <label>
                <span>目标人群</span>
                <input defaultValue="25–38 岁，关注肤色暗沉与通透感的都市女性" />
              </label>
              <label>
                <span>品牌调性</span>
                <div className="select-wrap">
                  <select defaultValue="premium">
                    <option value="premium">克制 · 高级 · 科研感</option>
                    <option value="natural">自然 · 松弛 · 清新</option>
                    <option value="energetic">明快 · 活力 · 年轻</option>
                  </select>
                  <ChevronDown size={15} />
                </div>
              </label>
            </div>
          </section>

          <section className="detail-form-card">
            <div className="form-section-head">
              <span className="number-chip">3</span>
              <div>
                <h2>输出设置</h2>
                <p>渠道、语言与页数会影响页面结构和预计成本。</p>
              </div>
            </div>
            <div className="output-options">
              <div className="option-field">
                <span>
                  <Store size={16} />
                  平台规格
                </span>
                <div className="selected-output-platform">
                  <span className="marketplace-mark">{selectedMarketplace.shortName}</span>
                  <span>
                    <strong>{selectedMarketplace.name}</strong>
                    <small>{selectedMarketplace.format}</small>
                  </span>
                </div>
              </div>
              <div className="option-field">
                <span>
                  <Languages size={16} />
                  内容语言
                </span>
                <div className="segmented-control">
                  <button
                    className={language === "zh-CN" ? "active" : ""}
                    onClick={() => setLanguage("zh-CN")}
                  >
                    简体中文
                  </button>
                  <button
                    className={language === "en-US" ? "active" : ""}
                    onClick={() => setLanguage("en-US")}
                  >
                    English
                  </button>
                </div>
              </div>
              <div className="option-field">
                <span>
                  <Boxes size={16} />
                  详情页数
                </span>
                <div className="page-count-control">
                  {[4, 6, 8].map((count) => (
                    <button
                      key={count}
                      className={pageCount === count ? "active" : ""}
                      onClick={() => setPageCount(count)}
                    >
                      {count} 页
                    </button>
                  ))}
                  <button aria-label="自定义页数">
                    <Plus size={15} />
                  </button>
                </div>
              </div>
            </div>
          </section>

          <section className="planning-card">
            <div className="planning-head">
              <div>
                <span className="number-chip number-chip--violet">4</span>
                <div>
                  <h2>页面规划</h2>
                  <p>已根据商品、渠道和卖点生成结构化计划，可在生成前调整。</p>
                </div>
              </div>
              <span className="plan-valid">
                <FileCheck2 size={15} />
                结构校验通过
              </span>
            </div>
            <div className="plan-list">
              {detailPages.map((page) => (
                <article key={page.page}>
                  <span className="plan-drag">
                    <GripVertical size={15} />
                  </span>
                  <i>0{page.page}</i>
                  <div>
                    <strong>{page.title}</strong>
                    <p>
                      {
                        [
                          "建立品牌氛围与核心产品印象",
                          "拆解三重焕亮成分与作用路径",
                          "以微距与流动质感表达轻盈吸收",
                          "呈现从暗沉到通透的视觉机制",
                          "用克制的信息图呈现实验数据",
                          "展示早晚使用次序与用量",
                        ][page.page - 1]
                      }
                    </p>
                  </div>
                  <span className={`quality-chip ${page.quality === "高质量" ? "high" : ""}`}>
                    {page.quality}
                  </span>
                  <span className={`page-status ${page.status}`}>
                    {page.status === "completed" && <CheckCircle2 size={14} />}
                    {page.status === "processing" && <LoaderCircle size={14} className="spin" />}
                    {page.status === "queued" && <Clock3 size={14} />}
                    {page.status === "completed"
                      ? "已完成"
                      : page.status === "processing"
                        ? "生成中"
                        : "待生成"}
                  </span>
                </article>
              ))}
            </div>
            <button className="link-button">
              <Plus size={15} />
              添加自定义页面
            </button>
          </section>

          <section className="generation-footer">
            <div className="estimate-grid">
              <span>
                <CircleDollarSign size={18} />
                <div>
                  <p>预计消耗</p>
                  <strong>18–22 次额度</strong>
                </div>
              </span>
              <span>
                <Clock3 size={18} />
                <div>
                  <p>预计耗时</p>
                  <strong>6–9 分钟</strong>
                </div>
              </span>
              <span>
                <WandSparkles size={18} />
                <div>
                  <p>质量分配</p>
                  <strong>3 高质量 + 3 均衡</strong>
                </div>
              </span>
            </div>
            <div className="generation-actions">
              <p>
                <Info size={14} />
                只会生成未完成页面，已成功的 3 页将直接复用。
              </p>
              <button className="primary-button">
                <Sparkles size={17} />
                继续生成剩余 3 页
                <ArrowRight size={17} />
              </button>
            </div>
          </section>
        </div>
        <HelpPanel mode="detail-pack" />
      </div>
    </AppShell>
  );
}
