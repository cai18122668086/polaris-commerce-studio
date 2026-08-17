"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  Clock3,
  Download,
  Image as ImageIcon,
  Mail,
  MessageCircle,
  MousePointer2,
  Paintbrush2,
  Search,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  X,
} from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { FEATURE_GROUPS } from "@/lib/feature-registry";
import {
  HELP_CATEGORIES,
  HELP_FAQS,
  HELP_TOPICS,
  SUPPORT_EMAIL,
  type HelpCategoryId,
} from "@/lib/help-center-content";

type CategoryFilter = "all" | HelpCategoryId;

const SUPPORT_MAILTO = `mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent(
  "极光商绘任务问题反馈",
)}&body=${encodeURIComponent(
  "请填写以下信息：\n\n注册邮箱：\n任务编号：\n功能名称：\n提交时间：\n当前状态或错误提示：\n已尝试的操作：\n\n请同时附上相关页面截图。",
)}`;

function includesQuery(parts: readonly string[], query: string) {
  if (!query) return true;
  const haystack = parts.join(" ").toLocaleLowerCase("zh-CN");
  return query
    .toLocaleLowerCase("zh-CN")
    .split(/\s+/)
    .filter(Boolean)
    .every((term) => haystack.includes(term));
}

export default function HelpPage() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<CategoryFilter>("all");
  const [openFaq, setOpenFaq] = useState<string | null>(HELP_FAQS[0]?.id ?? null);
  const searchRef = useRef<HTMLInputElement>(null);
  const normalizedQuery = query.trim();

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const isTyping = target?.matches("input, textarea, select, [contenteditable='true']");
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
        return;
      }
      if (event.key === "/" && !isTyping) {
        event.preventDefault();
        searchRef.current?.focus();
      }
    };

    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, []);

  const filteredTopics = useMemo(
    () =>
      HELP_TOPICS.filter(
        (topic) =>
          (category === "all" || topic.category === category) &&
          includesQuery(
            [topic.title, topic.summary, ...topic.items, ...topic.keywords],
            normalizedQuery,
          ),
      ),
    [category, normalizedQuery],
  );

  const filteredFaqs = useMemo(
    () =>
      HELP_FAQS.filter(
        (faq) =>
          (category === "all" || faq.category === category) &&
          includesQuery([faq.question, faq.answer, ...faq.keywords], normalizedQuery),
      ),
    [category, normalizedQuery],
  );

  const filteredFeatureGroups = useMemo(
    () =>
      FEATURE_GROUPS.map((group) => ({
        ...group,
        features: group.features.filter((feature) =>
          includesQuery(
            [
              feature.title,
              feature.shortTitle,
              feature.description,
              feature.inputHint,
              feature.outputHint,
              feature.guidance,
              ...feature.searchKeywords,
            ],
            normalizedQuery,
          ),
        ),
      })).filter((group) => group.features.length > 0),
    [normalizedQuery],
  );

  const featureCount = filteredFeatureGroups.reduce(
    (total, group) => total + group.features.length,
    0,
  );
  const resultCount = filteredTopics.length + filteredFaqs.length + featureCount;
  const visibleGuideCount = filteredTopics.length + filteredFaqs.length;
  const activeCategoryLabel =
    HELP_CATEGORIES.find((item) => item.id === category)?.label ?? "全部";

  return (
    <AppShell>
      <div className="help-page">
        <section className="help-hero" aria-labelledby="help-title">
          <span><BookOpen size={18} /> 极光商绘帮助中心</span>
          <h1 id="help-title">遇到问题，从真实操作场景开始找</h1>
          <p>搜索功能、任务状态、报错或保存期限，直接找到下一步该做什么。</p>
          <label>
            <Search size={19} aria-hidden="true" />
            <input
              ref={searchRef}
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索：上传失败、任务卡住、部分成功、30 天、国内电商主图…"
              aria-label="搜索帮助内容"
            />
            {query ? (
              <button
                type="button"
                className="help-search-clear"
                onClick={() => {
                  setQuery("");
                  searchRef.current?.focus();
                }}
                aria-label="清空搜索"
              >
                <X size={16} />
              </button>
            ) : (
              <kbd>Ctrl/⌘ K</kbd>
            )}
          </label>
        </section>

        <nav className="help-anchor-nav" aria-label="帮助中心页面目录">
          <a href="#quick-start">快速开始</a>
          <a href="#all-features">选择功能</a>
          <a href="#guides">使用指南</a>
          <a href="#faq">常见问题</a>
          <a href="#support">联系支持</a>
        </nav>

        <div className="help-page__content">
          <section id="quick-start" className="quick-start help-anchor-section">
            <div className="section-heading">
              <div>
                <span>快速开始</span>
                <h2>按实际流程完成第一次创作</h2>
                <p>提交后任务会继续运行，不需要停留在生成页面等待。</p>
              </div>
            </div>
            <div className="help-flow-grid">
              <article>
                <div className="help-flow__title">
                  <span><Paintbrush2 size={22} /></span>
                  <div><small>局部精修</small><h3>一句话改图</h3></div>
                </div>
                <ol>
                  <li><i><UploadCloud size={16} /></i><span><strong>上传清晰原图</strong><small>主体完整、细节可见</small></span></li>
                  <li><i><MousePointer2 size={16} /></i><span><strong>画出授权选区</strong><small>只覆盖允许变化的位置</small></span></li>
                  <li><i><MessageCircle size={16} /></i><span><strong>写清修改要求</strong><small>说明材质、颜色和保留项</small></span></li>
                  <li><i><CheckCircle2 size={16} /></i><span><strong>检查并下载</strong><small>核对选区外是否保持不变</small></span></li>
                </ol>
                <Link href="/workspace/local-edit">打开一句话改图 <ArrowRight size={16} /></Link>
              </article>

              <article className="violet">
                <div className="help-flow__title">
                  <span><Sparkles size={22} /></span>
                  <div><small>多页套图</small><h3>商品详情图</h3></div>
                </div>
                <ol>
                  <li><i><ImageIcon size={16} /></i><span><strong>添加同款素材</strong><small>不要混入不同商品或规格</small></span></li>
                  <li><i><MessageCircle size={16} /></i><span><strong>填写真实信息</strong><small>卖点、平台与画面要求</small></span></li>
                  <li><i><BookOpen size={16} /></i><span><strong>确认页面方案</strong><small>待确认时必须手动继续</small></span></li>
                  <li><i><Download size={16} /></i><span><strong>逐页审核下载</strong><small>失败项可以单独重试</small></span></li>
                </ol>
                <Link href="/workspace/detail-pack">创建商品详情图 <ArrowRight size={16} /></Link>
              </article>

              <article className="aurora">
                <div className="help-flow__title">
                  <span><ImageIcon size={22} /></span>
                  <div><small>固定交付六图</small><h3>国内电商主图</h3></div>
                </div>
                <ol>
                  <li><i><UploadCloud size={16} /></i><span><strong>上传同一商品</strong><small>提供主体与关键细节</small></span></li>
                  <li><i><MessageCircle size={16} /></i><span><strong>填写已核实卖点</strong><small>不填写无法验证的承诺</small></span></li>
                  <li><i><BookOpen size={16} /></i><span><strong>确认六图方案</strong><small>待确认时生成不会继续</small></span></li>
                  <li><i><Download size={16} /></i><span><strong>审核整套结果</strong><small>1 张搜索主图和 5 张轮播图</small></span></li>
                </ol>
                <Link href="/workspace/domestic-main-image">创建国内电商主图 <ArrowRight size={16} /></Link>
              </article>
            </div>
          </section>

          <section id="all-features" className="guide-library help-anchor-section">
            <div className="section-heading">
              <div>
                <span>全部功能</span>
                <h2>根据输入素材和预期交付选择工具</h2>
                <p>这里直接读取当前功能目录；产品新增或调整功能时，帮助中心会同步更新。</p>
              </div>
            </div>
            {filteredFeatureGroups.length ? (
              <div className="help-feature-groups">
                {filteredFeatureGroups.map((group) => (
                  <section key={group.category} aria-labelledby={`feature-group-${group.category}`}>
                    <h3 id={`feature-group-${group.category}`}>{group.label}</h3>
                    <div className="help-feature-grid">
                      {group.features.map((feature) => {
                        const Icon = feature.icon;
                        return (
                          <Link key={feature.id} href={feature.route} className="help-feature-card">
                            <span className={`tool-icon ${feature.tone}`} aria-hidden="true"><Icon size={20} /></span>
                            <span className="help-feature-card__copy">
                              <strong>{feature.title}</strong>
                              <small>{feature.description}</small>
                              <span><b>需要</b>{feature.inputHint}</span>
                              <span><b>得到</b>{feature.outputHint}</span>
                            </span>
                            <ArrowRight size={16} aria-hidden="true" />
                          </Link>
                        );
                      })}
                    </div>
                  </section>
                ))}
              </div>
            ) : null}
          </section>

          <section id="guides" className="guide-library help-anchor-section">
            <div className="section-heading">
              <div>
                <span>使用指南</span>
                <h2>针对当前情况采取下一步</h2>
                <p>内容按真实页面状态整理，不需要从不存在的“指南文章”继续跳转。</p>
              </div>
            </div>

            <div className="help-filter-bar" aria-label="按主题筛选帮助内容">
              {HELP_CATEGORIES.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={category === item.id ? "active" : ""}
                  onClick={() => setCategory(item.id)}
                  aria-pressed={category === item.id}
                >
                  {item.label}
                </button>
              ))}
            </div>

            {(normalizedQuery || category !== "all") && (
              <p className="help-search-summary" role="status">
                {normalizedQuery ? `“${normalizedQuery}”` : activeCategoryLabel}：找到 {normalizedQuery ? resultCount : visibleGuideCount} 条相关内容
              </p>
            )}

            {filteredTopics.length ? (
              <div className="help-guide-list">
                {filteredTopics.map((topic) => (
                  <article key={topic.id} id={topic.id}>
                    <div>
                      {topic.category === "retention" ? <Clock3 size={21} /> : topic.category === "troubleshooting" ? <AlertTriangle size={21} /> : topic.category === "assets" ? <UploadCloud size={21} /> : topic.category === "tasks" ? <CheckCircle2 size={21} /> : <BookOpen size={21} />}
                    </div>
                    <section>
                      <small>{HELP_CATEGORIES.find((item) => item.id === topic.category)?.label}</small>
                      <h3>{topic.title}</h3>
                      <p>{topic.summary}</p>
                      <ul>{topic.items.map((item) => <li key={item}>{item}</li>)}</ul>
                    </section>
                  </article>
                ))}
              </div>
            ) : null}
          </section>

          <section id="retention-summary" className="help-retention-notice help-anchor-section" aria-labelledby="retention-title">
            <span><ShieldCheck size={23} /></span>
            <div>
              <small>请提前下载</small>
              <h2 id="retention-title">用户内容保存 30 天，到期不可恢复</h2>
              <p>上传素材从上传成功起、生成图片从创建成功起、终态任务记录从结束起、草稿从创建起，分别保存 30 天。到期后相关内容会被清理且不可恢复。</p>
            </div>
            <Link href="/jobs">前往生成记录 <ArrowRight size={16} /></Link>
          </section>

          <section id="faq" className="faq-section help-anchor-section">
            <div className="section-heading">
              <div><span>常见问题</span><h2>用户最常遇到的情况</h2></div>
            </div>
            <div className="faq-layout">
              <div>
                {filteredFaqs.length ? (
                  <div className="faq-list">
                    {filteredFaqs.map((item) => {
                      const open = openFaq === item.id;
                      const answerId = `faq-answer-${item.id}`;
                      return (
                        <article key={item.id} className={open ? "open" : ""}>
                          <button
                            type="button"
                            onClick={() => setOpenFaq(open ? null : item.id)}
                            aria-expanded={open}
                            aria-controls={answerId}
                          >
                            <strong>{item.question}</strong><ChevronDown size={18} />
                          </button>
                          <div id={answerId} aria-hidden={!open}><p>{item.answer}</p></div>
                        </article>
                      );
                    })}
                  </div>
                ) : null}

                {resultCount === 0 ? (
                  <div className="help-empty" role="status">
                    <CircleHelp size={28} />
                    <h3>没有找到完全匹配的内容</h3>
                    <p>换一个任务状态、功能名称或错误关键词，或者把任务编号和截图发给支持邮箱。</p>
                    <button type="button" className="secondary-button" onClick={() => { setQuery(""); setCategory("all"); }}>
                      清除搜索和筛选
                    </button>
                  </div>
                ) : null}
              </div>

              <aside id="support" className="support-card help-anchor-section">
                <span><Mail size={23} /></span>
                <h3>仍然没有解决？</h3>
                <p>邮件中请附上注册邮箱、任务编号、功能名称、提交时间、当前状态或错误提示、已尝试的操作和页面截图，方便直接定位。</p>
                <a className="primary-button" href={SUPPORT_MAILTO}>发送问题邮件</a>
                <small>{SUPPORT_EMAIL} · 回复时间以实际处理进度为准</small>
                <Link href="/legal/privacy">查看隐私政策</Link>
              </aside>
            </div>
          </section>
        </div>
      </div>
    </AppShell>
  );
}
