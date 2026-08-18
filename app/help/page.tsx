"use client";

import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import {
  ArrowRight,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  MessageCircle,
  MousePointer2,
  Search,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  X,
} from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { HELP_FAQS } from "@/lib/help-center-content";

type Faq = {
  id: string;
  question: string;
  answer: string;
  keywords: readonly string[];
};

const uploadFaqs: readonly Faq[] = [
  {
    id: "upload-local-edit",
    question: "如何上传一句话改图的原始图片？",
    answer:
      "进入一句话改图后，点击上传区域或将图片拖入页面即可。建议上传清晰、主体完整的 JPG 或 PNG 图片，上传完成后再绘制授权选区。",
    keywords: ["上传", "原始图片", "一句话改图", "拖拽", "文件"],
  },
  {
    id: "upload-format-size",
    question: "上传图片支持哪些格式和大小？",
    answer:
      "目前建议使用 JPG、JPEG 或 PNG 格式。请尽量上传主体清晰、未被过度压缩的图片；如果上传失败，可以先压缩文件体积或更换浏览器重试。",
    keywords: ["上传", "格式", "大小", "JPG", "JPEG", "PNG", "图片"],
  },
  {
    id: "upload-preview-missing",
    question: "上传后图片没有显示怎么办？",
    answer:
      "先确认文件仍在上传状态，等待缩略图加载完成；如果长时间没有反应，请刷新页面后重新上传，并检查网络连接与文件格式。已经成功提交的任务不会因为刷新而重复创建。",
    keywords: ["上传", "没有显示", "加载", "失败", "刷新", "网络"],
  },
  {
    id: "upload-multi-angle-grouping",
    question: "上传多角度商品图时应该如何分组？",
    answer:
      "同一商品的正面、45 度和侧面照片应放在同一个分组中。不同款式、颜色或规格请分开上传，避免系统把不同商品误判为同一组。",
    keywords: ["上传", "多角度", "商品图", "分组", "素材"],
  },
];

const faqs: readonly Faq[] = [...uploadFaqs, ...HELP_FAQS];

const guideSections = [
  {
    icon: UploadCloud,
    title: "1. 准备并上传素材",
    body: "选择主体完整、光线稳定的图片。进入对应工具后，点击上传区域或直接拖入文件；缩略图出现并加载完成后，才算上传成功。",
    tips: "建议：JPG / PNG，主体清晰，边长 1200px 以上。",
  },
  {
    icon: MousePointer2,
    title: "2. 明确需要修改的范围",
    body: "使用一句话改图时，请圈选允许发生变化的区域。选区越准确，结果越容易符合预期；不希望变化的内容不要包含在选区内。",
    tips: "建议：选区边缘比目标多覆盖 8–16px，方便自然融合。",
  },
  {
    icon: MessageCircle,
    title: "3. 写清楚你的目标",
    body: "用一句话描述想要的材质、颜色、姿态或场景，并补充需要保留的内容。避免只写“改好看一点”这类无法执行的描述。",
    tips: "示例：将背景改为浅灰色，保留人物脸部、发型和衣服纹理。",
  },
  {
    icon: Sparkles,
    title: "4. 提交后查看任务状态",
    body: "提交后可以在任务列表查看处理进度。结果生成完成后再下载；如果任务失败，只需按失败页面提示单独重试，不会重复创建已经完成的项目。",
    tips: "建议：网络不稳定时不要连续点击提交，先查看任务状态。",
  },
];

export default function HelpPage() {
  const [openFaq, setOpenFaq] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchFocused, setSearchFocused] = useState(false);
  const [guideOpen, setGuideOpen] = useState(false);
  const [contactOpen, setContactOpen] = useState(false);
  const faqRefs = useRef<Array<HTMLElement | null>>([]);

  const normalizedQuery = searchQuery.trim().toLowerCase();
  const filteredFaqs = normalizedQuery
    ? faqs
        .map((item, index) => ({ item, index }))
        .filter(({ item }) =>
          [item.question, item.answer, ...item.keywords]
            .join(" ")
            .toLowerCase()
            .includes(normalizedQuery),
        )
    : [];

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        document.querySelector<HTMLInputElement>(".help-search input")?.focus();
      }
      if (event.key === "Escape") {
        setGuideOpen(false);
        setContactOpen(false);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    document.body.style.overflow = guideOpen || contactOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [guideOpen, contactOpen]);

  const selectSearchResult = (index: number) => {
    setOpenFaq(index);
    setSearchQuery("");
    setSearchFocused(false);
    requestAnimationFrame(() => {
      faqRefs.current[index]?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  };

  return (
    <AppShell>
      <div className="help-page">
        <section className="help-hero">
          <span><BookOpen size={18} /> 极光商绘帮助中心</span>
          <h1>需要帮助？从这里开始</h1>
          <p>先搜索问题，或打开使用指南，快速找到下一步怎么做。</p>
          <div className="help-search-wrap">
            <label className="help-search">
              <Search size={19} />
              <input
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                onFocus={() => setSearchFocused(true)}
                placeholder="搜索问题，例如：上传、如何画选区、任务失败"
                aria-label="搜索帮助问题"
                aria-controls="help-search-results"
              />
              <kbd>Ctrl K</kbd>
            </label>
            {searchFocused && normalizedQuery ? (
              <div className="help-search-results" id="help-search-results" role="listbox">
                {filteredFaqs.length > 0 ? (
                  filteredFaqs.map(({ item, index }) => (
                    <button key={item.id} onMouseDown={() => selectSearchResult(index)} role="option" aria-selected="false">
                      <CircleHelp size={16} />
                      <span>
                        <strong>{item.question}</strong>
                        <small>{item.answer}</small>
                      </span>
                      <ArrowRight size={15} />
                    </button>
                  ))
                ) : (
                  <div className="help-search-empty">
                    <Search size={17} />
                    <span>没有找到相关问题，试试“上传”“选区”或“任务失败”。</span>
                  </div>
                )}
              </div>
            ) : null}
          </div>
        </section>

        <div className="help-page__content">
          <section className="guide-entry-section" aria-labelledby="guide-entry-title">
            <div className="section-heading">
              <div>
                <span>使用指南</span>
                <h2 id="guide-entry-title">需要详细了解怎么用？</h2>
                <p>点击打开完整操作说明，按照步骤完成图片创作。</p>
              </div>
            </div>
            <button className="guide-launcher" onClick={() => setGuideOpen(true)} aria-haspopup="dialog">
              <span className="guide-launcher__icon"><BookOpen size={24} /></span>
              <span className="guide-launcher__copy">
                <strong>打开使用指南</strong>
                <small>上传素材、设置选区、填写描述、查看任务结果</small>
              </span>
              <span className="guide-launcher__action">查看详情 <ArrowRight size={16} /></span>
            </button>
          </section>

          <section className="faq-section" aria-labelledby="faq-title">
            <div className="section-heading">
              <div>
                <span>常见问题</span>
                <h2 id="faq-title">你可能正在寻找</h2>
                <p>点击问题查看答案，也可以使用上方搜索框直接定位。</p>
              </div>
            </div>
            <div className="faq-layout">
              <div className="faq-list">
                {faqs.map((item, index) => (
                  <article
                    key={item.id}
                    ref={(element) => { faqRefs.current[index] = element; }}
                    className={openFaq === index ? "open" : ""}
                    id={`faq-${index + 1}`}
                  >
                    <button onClick={() => setOpenFaq(openFaq === index ? -1 : index)} aria-expanded={openFaq === index}>
                      <strong>{item.question}</strong>
                      <ChevronDown size={18} />
                    </button>
                    <div><p>{item.answer}</p></div>
                  </article>
                ))}
              </div>
              <aside className="support-card">
                <span><MessageCircle size={23} /></span>
                <h3>仍然没有解决？</h3>
                <p>在线联系工作人员，添加企业微信后描述你遇到的任务状态和操作步骤。</p>
                <button className="primary-button" onClick={() => setContactOpen(true)} aria-haspopup="dialog">
                  在线联系
                  <ArrowRight size={16} />
                </button>
                <small>工作日 09:30–18:30 · 添加后会尽快回复</small>
              </aside>
            </div>
          </section>
        </div>
      </div>

      {guideOpen ? (
        <div className="help-modal-backdrop" role="presentation" onMouseDown={() => setGuideOpen(false)}>
          <section className="help-modal guide-modal" role="dialog" aria-modal="true" aria-labelledby="guide-modal-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="help-modal__header">
              <div>
                <span><BookOpen size={17} /> 使用指南</span>
                <h2 id="guide-modal-title">从上传到下载，完成一次创作</h2>
                <p>按下面的顺序操作，就能更稳定地得到符合预期的结果。</p>
              </div>
              <button className="help-modal__close" onClick={() => setGuideOpen(false)} aria-label="关闭使用指南"><X size={19} /></button>
            </header>
            <div className="guide-modal__body">
              <div className="guide-modal__steps">
                {guideSections.map((section) => {
                  const Icon = section.icon;
                  return (
                    <article key={section.title}>
                      <span className="guide-step-icon"><Icon size={19} /></span>
                      <div>
                        <h3>{section.title}</h3>
                        <p>{section.body}</p>
                        <small><CheckCircle2 size={14} /> {section.tips}</small>
                      </div>
                    </article>
                  );
                })}
              </div>
              <div className="guide-modal__notice">
                <ShieldCheck size={18} />
                <div><strong>小提醒</strong><p>选区外内容会被保留；不要连续点击提交，先在任务列表确认当前状态。</p></div>
              </div>
            </div>
            <footer className="help-modal__footer">
              <span>遇到问题？可以在常见问题中搜索关键词。</span>
              <button className="secondary-button" onClick={() => setGuideOpen(false)}>知道了</button>
            </footer>
          </section>
        </div>
      ) : null}

      {contactOpen ? (
        <div className="help-modal-backdrop" role="presentation" onMouseDown={() => setContactOpen(false)}>
          <section className="help-modal contact-modal" role="dialog" aria-modal="true" aria-labelledby="contact-modal-title" onMouseDown={(event) => event.stopPropagation()}>
            <button className="help-modal__close contact-modal__close" onClick={() => setContactOpen(false)} aria-label="关闭在线联系"><X size={19} /></button>
            <div className="contact-modal__icon"><MessageCircle size={24} /></div>
            <h2 id="contact-modal-title">在线联系</h2>
            <p>请扫描二维码，添加企业微信联系我们。添加时可以备注你的账号和遇到的问题。</p>
            <div className="contact-qr"><Image src="/contact-wechat-qr.jpg" alt="腾利科技企业微信二维码" width={330} height={330} unoptimized /></div>
            <strong>扫码添加企业微信</strong>
            <small>工作日 09:30–18:30 · 我们会尽快回复</small>
          </section>
        </div>
      ) : null}
    </AppShell>
  );
}
