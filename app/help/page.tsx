"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  FileQuestion,
  Image as ImageIcon,
  MessageCircle,
  MousePointer2,
  Paintbrush2,
  PlayCircle,
  Search,
  ShieldCheck,
  Sparkles,
  UploadCloud,
} from "lucide-react";
import { AppShell } from "@/components/app-shell";

const faqs = [
  {
    question: "一句话改图为什么需要确认授权选区？",
    answer:
      "选区会作为本次任务的修改边界，用于明确允许调整的区域；请尽量准确圈选需要修改的位置。",
  },
  {
    question: "详情图任务失败后会重复创建全部项目吗？",
    answer:
      "不会。取消只会作用于当前仍可取消的任务，已经完成的任务和结果会继续保留。",
  },
  {
    question: "多角度商品图应该如何拍摄？",
    answer:
      "建议保持相近光线、焦段和背景，至少包含正面、45 度与侧面。不要在同一商品分组中混入不同款式或规格。",
  },
  {
    question: "国内电商主图会生成哪些图片？",
    answer:
      "每个任务会先确认六图方案，再依次生成 1 张搜索主图和 5 张轮播图。建议上传 1–8 张同一商品的真实图片，并只填写已经核实的卖点。",
  },
  {
    question: "图片结果会被公开或用于展示吗？",
    answer:
      "当前工作台中的图片默认只在你的素材与任务中使用。对外展示、协作或分享功能后续会提供独立授权设置。",
  },
];

export default function HelpPage() {
  const [openFaq, setOpenFaq] = useState(0);

  return (
    <AppShell>
      <div className="help-page">
        <section className="help-hero">
          <span><BookOpen size={18} /> 极光商绘帮助中心</span>
          <h1>需要帮助？从这里开始</h1>
          <p>查找操作指南、最佳实践与常见问题，让每一次创作流程更顺畅。</p>
          <label>
            <Search size={19} />
            <input placeholder="搜索问题，例如：如何画选区、如何重试失败页面" />
            <kbd>⌘ K</kbd>
          </label>
        </section>

        <div className="help-page__content">
          <section className="quick-start">
            <div className="section-heading">
              <div>
                <span>快速开始</span>
                <h2>选择你的创作目标</h2>
                <p>按照清晰步骤，几分钟内完成第一次图片创作。</p>
              </div>
            </div>
            <div className="help-flow-grid">
              <article>
                <div className="help-flow__title">
                  <span><Paintbrush2 size={22} /></span>
                  <div>
                    <small>约 2 分钟</small>
                    <h3>完成一次“一句话改图”</h3>
                  </div>
                </div>
                <ol>
                  <li><i><UploadCloud size={16} /></i><span><strong>上传原始图片</strong><small>建议边长 1200px 以上</small></span></li>
                  <li><i><MousePointer2 size={16} /></i><span><strong>绘制授权选区</strong><small>只圈选允许变化的区域</small></span></li>
                  <li><i><MessageCircle size={16} /></i><span><strong>描述期望效果</strong><small>写清材质、颜色与保留项</small></span></li>
                  <li><i><ShieldCheck size={16} /></i><span><strong>查看任务处理状态</strong><small>结果可用后即可下载处理图片</small></span></li>
                </ol>
                <Link href="/workspace/local-edit">
                  打开一句话改图
                  <ArrowRight size={16} />
                </Link>
              </article>
              <article className="violet">
                <div className="help-flow__title">
                  <span><Sparkles size={22} /></span>
                  <div>
                    <small>约 8 分钟</small>
                    <h3>验证一套商品详情规划</h3>
                  </div>
                </div>
                <ol>
                  <li><i><ImageIcon size={16} /></i><span><strong>添加多角度素材</strong><small>同一商品进入一个分组</small></span></li>
                  <li><i><FileQuestion size={16} /></i><span><strong>填写商品与卖点</strong><small>使用真实、可验证的信息</small></span></li>
                  <li><i><BookOpen size={16} /></i><span><strong>确认页面规划</strong><small>生成前可调整叙事结构</small></span></li>
                  <li><i><CheckCircle2 size={16} /></i><span><strong>检查任务处理结果</strong><small>如暂无图片，请稍后查看任务状态</small></span></li>
                </ol>
                <Link href="/workspace/detail-pack">
                  创建商品详情图
                  <ArrowRight size={16} />
                </Link>
              </article>
              <article className="aurora">
                <div className="help-flow__title">
                  <span><ImageIcon size={22} /></span>
                  <div>
                    <small>固定交付 6 张</small>
                    <h3>一键生成国内电商主图</h3>
                  </div>
                </div>
                <ol>
                  <li><i><UploadCloud size={16} /></i><span><strong>上传真实商品图</strong><small>同一商品 1–8 张</small></span></li>
                  <li><i><FileQuestion size={16} /></i><span><strong>填写已核实卖点</strong><small>避免夸大或未知信息</small></span></li>
                  <li><i><BookOpen size={16} /></i><span><strong>确认整组六图方案</strong><small>生成前检查每张用途</small></span></li>
                  <li><i><CheckCircle2 size={16} /></i><span><strong>查看并下载结果</strong><small>1 张主图 + 5 张轮播图</small></span></li>
                </ol>
                <Link href="/workspace/domestic-main-image">
                  创建国内电商主图
                  <ArrowRight size={16} />
                </Link>
              </article>
            </div>
          </section>

          <section className="guide-library">
            <div className="section-heading">
              <div>
                <span>指南库</span>
                <h2>按主题浏览</h2>
              </div>
            </div>
            <div className="guide-grid">
              {[
                { icon: PlayCircle, title: "新手入门", count: "6 篇指南", tone: "blue", text: "了解工作台、额度与任务状态" },
                { icon: Paintbrush2, title: "一句话改图", count: "12 篇指南", tone: "indigo", text: "选区技巧、提示词与任务状态" },
                { icon: Sparkles, title: "商品详情图", count: "9 篇指南", tone: "violet", text: "平台选择、素材分组、页面规划与断点续作" },
                { icon: ImageIcon, title: "素材与文件", count: "5 篇指南", tone: "cyan", text: "格式规范、清晰度与资产复用" },
                { icon: ShieldCheck, title: "安全与隐私", count: "4 篇指南", tone: "green", text: "图片处理、权限与数据保护" },
                { icon: CircleHelp, title: "异常处理", count: "7 篇指南", tone: "orange", text: "任务失败、网络恢复与重试" },
              ].map((item) => {
                const Icon = item.icon;
                return (
                  <button key={item.title}>
                    <span className={`guide-icon tone-${item.tone}`}><Icon size={21} /></span>
                    <div><strong>{item.title}</strong><p>{item.text}</p><small>{item.count}</small></div>
                    <ArrowRight size={16} />
                  </button>
                );
              })}
            </div>
          </section>

          <section className="faq-section">
            <div className="section-heading">
              <div>
                <span>常见问题</span>
                <h2>你可能正在寻找</h2>
              </div>
            </div>
            <div className="faq-layout">
              <div className="faq-list">
                {faqs.map((item, index) => (
                  <article key={item.question} className={openFaq === index ? "open" : ""}>
                    <button onClick={() => setOpenFaq(openFaq === index ? -1 : index)}>
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
                <p>描述你遇到的任务状态和操作步骤，我们会给出更有针对性的排查建议。</p>
                <button className="primary-button">联系在线支持</button>
                <small>工作日 09:30–18:30 · 平均 5 分钟响应</small>
              </aside>
            </div>
          </section>
        </div>
      </div>
    </AppShell>
  );
}
