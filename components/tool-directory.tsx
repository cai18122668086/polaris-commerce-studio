"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  LayoutGrid,
  Search,
  Sparkles,
} from "lucide-react";
import { futureTools, toolGroups } from "@/lib/tool-registry";
import { productImages } from "@/lib/mock-data";

export function ToolDirectory() {
  const [query, setQuery] = useState("");
  const [activeGroup, setActiveGroup] = useState("全部工具");
  const searchRef = useRef<HTMLInputElement>(null);
  const creativeGroups = toolGroups.filter((group) => group.label !== "资产管理");
  const availableTools = creativeGroups.flatMap((group) =>
    group.items.map((item) => ({ ...item, group: group.label })),
  );
  const keyword = query.trim().toLowerCase();
  const filteredTools = availableTools.filter((tool) => {
    const inGroup = activeGroup === "全部工具" || tool.group === activeGroup;
    return (
      inGroup &&
      (!keyword ||
        `${tool.title} ${tool.description} ${tool.group}`.toLowerCase().includes(keyword))
    );
  });

  useEffect(() => {
    const focusSearch = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", focusSearch);
    return () => window.removeEventListener("keydown", focusSearch);
  }, []);

  return (
    <section className="tool-market" id="tools">
      <div className="tool-market__head">
        <div>
          <span>AI 功能大全</span>
          <h1>你想处理哪类商品图？</h1>
          <p>选择功能，上传图片，就可以开始创作。</p>
        </div>
        <label className="market-search">
          <Search size={18} />
          <input
            ref={searchRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索你需要的功能"
            aria-label="搜索 AI 功能"
          />
          <kbd>⌘ K</kbd>
        </label>
      </div>

      <div className="tool-market__body">
        <aside className="market-category" aria-label="功能分类">
          <p>功能分类</p>
          <button
            className={activeGroup === "全部工具" ? "active" : ""}
            onClick={() => setActiveGroup("全部工具")}
          >
            <span>
              <LayoutGrid size={17} />
              全部工具
            </span>
            <i>{availableTools.length}</i>
          </button>
          {creativeGroups.map((group) => {
            const Icon = group.items[0].icon;
            return (
              <button
                key={group.label}
                className={activeGroup === group.label ? "active" : ""}
                onClick={() => setActiveGroup(group.label)}
              >
                <span>
                  <Icon size={17} />
                  {group.label}
                </span>
                <i>{group.items.length}</i>
              </button>
            );
          })}
          <div className="category-note">
            <Sparkles size={15} />
            <span>
              <strong>更多能力持续接入</strong>
              <small>新工具会自动出现在对应分类中</small>
            </span>
          </div>
        </aside>

        <div className="market-content">
          <div className="market-section-title">
            <div>
              <h2>{activeGroup === "全部工具" ? "精选功能" : activeGroup}</h2>
              <p>当前开放 {filteredTools.length} 个功能</p>
            </div>
            <span>
              <i />
              所有展示功能均可使用
            </span>
          </div>

          {filteredTools.length ? (
            <div className="visual-tool-grid">
              {filteredTools.map((tool) => {
                const Icon = tool.icon;
                const isLocalEdit = tool.href.includes("local-edit");
                return (
                  <Link href={tool.href} key={tool.href} className="visual-tool-card">
                    <div
                      className={`visual-tool-card__preview ${
                        isLocalEdit ? "preview-local" : "preview-detail"
                      }`}
                    >
                      <img
                        src={isLocalEdit ? productImages.headphones : productImages.skincare}
                        alt=""
                      />
                      {isLocalEdit ? (
                        <>
                          <span className="preview-selection">
                            <i />
                            仅修改选区
                          </span>
                          <em>选区外保持原样</em>
                        </>
                      ) : (
                        <div className="preview-pages">
                          <span>01</span>
                          <span>02</span>
                          <span>03</span>
                        </div>
                      )}
                    </div>
                    <div className="visual-tool-card__content">
                      <div className="visual-tool-card__title">
                        <span className={`tool-icon tone-${tool.tone}`}>
                          <Icon size={21} />
                        </span>
                        <span>
                          <strong>{tool.title}</strong>
                          <small>{tool.description}</small>
                        </span>
                        {tool.badge && <em>{tool.badge}</em>}
                      </div>
                      <div className="tool-capabilities">
                        {(isLocalEdit
                          ? ["画笔选区", "材质替换", "像素锁定"]
                          : ["多图分析", "页面规划", "批量成套"]
                        ).map((item) => (
                          <span key={item}>
                            <Check size={11} />
                            {item}
                          </span>
                        ))}
                      </div>
                      <b>
                        立即使用
                        <ArrowRight size={16} />
                      </b>
                    </div>
                  </Link>
                );
              })}
            </div>
          ) : (
            <div className="market-empty">
              <Search size={24} />
              <strong>没有找到匹配功能</strong>
              <p>试试“局部修改”或“详情图”。</p>
              <button
                onClick={() => {
                  setQuery("");
                  setActiveGroup("全部工具");
                }}
              >
                查看全部工具
              </button>
            </div>
          )}

          <div className="coming-tools">
            <div>
              <span>即将上线</span>
              <p>这些能力完成后会直接加入功能大全，无需改变首页结构。</p>
            </div>
            <div>
              {futureTools.map((tool) => {
                const Icon = tool.icon;
                return (
                  <span key={tool.label}>
                    <Icon size={16} />
                    {tool.label}
                    <i>规划中</i>
                  </span>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
