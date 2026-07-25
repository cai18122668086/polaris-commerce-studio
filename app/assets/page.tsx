"use client";

import { useMemo, useState } from "react";
import {
  ArrowUpRight,
  CalendarDays,
  Check,
  ChevronDown,
  CloudUpload,
  Filter,
  FolderOpen,
  Grid3X3,
  Image as ImageIcon,
  LayoutGrid,
  List,
  MoreHorizontal,
  Paintbrush2,
  Search,
  Sparkles,
  Upload,
} from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { mockAssets } from "@/lib/mock-data";

const sourceOptions = ["全部来源", "素材上传", "局部修改", "商品详情图"];

export default function AssetsPage() {
  const [source, setSource] = useState("全部来源");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const assets = useMemo(
    () =>
      mockAssets.filter(
        (asset) =>
          (source === "全部来源" || asset.source === source) &&
          asset.title.toLowerCase().includes(query.toLowerCase()),
      ),
    [query, source],
  );

  const toggleSelected = (id: string) =>
    setSelected((items) =>
      items.includes(id) ? items.filter((item) => item !== id) : [...items, id],
    );

  return (
    <AppShell>
      <div className="content-page assets-page">
        <div className="page-title-row">
          <div>
            <span>资产管理</span>
            <h1>个人素材库</h1>
            <p>统一管理原始素材与生成结果，并在不同工作流之间复用。</p>
          </div>
          <button className="primary-button">
            <Upload size={17} />
            上传素材
          </button>
        </div>

        <section className="asset-overview">
          <div className="storage-card">
            <span>
              <FolderOpen size={21} />
            </span>
            <div>
              <p>素材空间</p>
              <strong>3.8 GB <small>/ 10 GB</small></strong>
              <i><b style={{ width: "38%" }} /></i>
            </div>
            <em>可用 6.2 GB</em>
          </div>
          <div>
            <ImageIcon size={19} />
            <span>
              <p>原始素材</p>
              <strong>146</strong>
            </span>
          </div>
          <div>
            <Sparkles size={19} />
            <span>
              <p>生成结果</p>
              <strong>312</strong>
            </span>
          </div>
          <div>
            <CloudUpload size={19} />
            <span>
              <p>本周新增</p>
              <strong>28</strong>
            </span>
          </div>
        </section>

        <section className="asset-library">
          <div className="asset-library__head">
            <div className="asset-tabs">
              <button className="active">全部素材 <span>458</span></button>
              <button>原始图片 <span>146</span></button>
              <button>生成结果 <span>312</span></button>
            </div>
            <div className="view-toggle">
              <button className="active" aria-label="网格视图"><LayoutGrid size={17} /></button>
              <button aria-label="列表视图"><List size={17} /></button>
            </div>
          </div>
          <div className="asset-toolbar">
            <label className="search-field">
              <Search size={16} />
              <input
                placeholder="搜索素材名称"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            <div className="select-filter">
              <Filter size={15} />
              <select value={source} onChange={(event) => setSource(event.target.value)}>
                {sourceOptions.map((item) => <option key={item}>{item}</option>)}
              </select>
              <ChevronDown size={14} />
            </div>
            <button>
              <CalendarDays size={16} />
              最近 30 天
            </button>
            <button>
              <Grid3X3 size={16} />
              全部尺寸
            </button>
            <span className="asset-count">{assets.length} 个素材</span>
          </div>
          {selected.length > 0 && (
            <div className="selection-toolbar">
              <span>
                <i><Check size={13} /></i>
                已选择 {selected.length} 项
              </span>
              <button>
                <Paintbrush2 size={15} />
                带入局部修改
              </button>
              <button>
                <Sparkles size={15} />
                创建详情套图
              </button>
              <button onClick={() => setSelected([])}>取消选择</button>
            </div>
          )}
          <div className="asset-grid">
            <button className="upload-asset-card">
              <span><Upload size={24} /></span>
              <strong>上传新素材</strong>
              <p>拖拽图片到这里，或点击选择文件</p>
              <small>JPG / PNG / WEBP · 单张不超过 20MB</small>
            </button>
            {assets.map((asset) => (
              <article key={asset.id} className={`asset-card ${selected.includes(asset.id) ? "selected" : ""}`}>
                <div className={`asset-image tone-${asset.tone}`}>
                  <img src={asset.image} alt={asset.title} />
                  <button
                    className="asset-check"
                    onClick={() => toggleSelected(asset.id)}
                    aria-label={`选择 ${asset.title}`}
                  >
                    {selected.includes(asset.id) && <Check size={14} />}
                  </button>
                  <span>{asset.kind}</span>
                  <button className="asset-more" aria-label="更多操作"><MoreHorizontal size={16} /></button>
                  <div className="asset-hover-actions">
                    <button>
                      <Paintbrush2 size={15} />
                      局部修改
                    </button>
                    <button>
                      <Sparkles size={15} />
                      详情套图
                    </button>
                  </div>
                </div>
                <div className="asset-info">
                  <div>
                    <strong>{asset.title}</strong>
                    <button aria-label="打开素材"><ArrowUpRight size={15} /></button>
                  </div>
                  <p>{asset.source} · {asset.createdAt}</p>
                  <span>{asset.size}</span>
                </div>
              </article>
            ))}
          </div>
          <div className="asset-safe-note">
            <Check size={14} />
            素材库暂不提供批量删除，避免误删正在被任务引用的图片。
          </div>
        </section>
      </div>
    </AppShell>
  );
}
