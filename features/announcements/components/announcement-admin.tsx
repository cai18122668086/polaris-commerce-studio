"use client";

import { useState } from "react";
import { Archive, Bell, Check, Eye, FilePlus2, Loader2, Megaphone, Pencil, Pin, Plus, RefreshCw, Send } from "lucide-react";

import {
  useAdminAnnouncements,
  useAnnouncementAdminAccess,
  useArchiveAnnouncement,
  useCreateAnnouncement,
  usePublishAnnouncement,
  useUpdateAnnouncement,
} from "@/features/announcements/api/announcements";
import { errorMessage } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";

type Announcement = components["schemas"]["AnnouncementResponse"];
type AnnouncementKind = "info" | "success" | "warning" | "maintenance";
type AnnouncementFilter = "all" | "draft" | "published" | "archived";

type FormState = {
  title: string;
  summary: string;
  content: string;
  kind: AnnouncementKind;
  link_url: string;
  starts_at: string;
  ends_at: string;
  is_pinned: boolean;
};

const EMPTY_FORM: FormState = {
  title: "",
  summary: "",
  content: "",
  kind: "info",
  link_url: "",
  starts_at: "",
  ends_at: "",
  is_pinned: false,
};

const kindLabels: Record<AnnouncementKind, string> = {
  info: "普通公告",
  success: "产品更新",
  warning: "重要提醒",
  maintenance: "系统维护",
};

const statusLabels: Record<AnnouncementFilter, string> = {
  all: "全部",
  draft: "草稿",
  published: "已发布",
  archived: "已归档",
};

function toDateInput(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function toIso(value: string) {
  return value ? new Date(value).toISOString() : null;
}

function formFromAnnouncement(item: Announcement): FormState {
  return {
    title: item.title,
    summary: item.summary ?? "",
    content: item.content,
    kind: item.kind,
    link_url: item.link_url ?? "",
    starts_at: toDateInput(item.starts_at),
    ends_at: toDateInput(item.ends_at),
    is_pinned: item.is_pinned,
  };
}

function formatDate(value: string | null) {
  if (!value) return "未设置";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

export function AnnouncementAdmin({
  filter,
  onFilterChange,
}: {
  filter: AnnouncementFilter;
  onFilterChange: (filter: AnnouncementFilter) => void;
}) {
  const access = useAnnouncementAdminAccess();
  const canManage = access.data?.can_manage === true;
  const announcements = useAdminAnnouncements(filter, canManage);
  const createMutation = useCreateAnnouncement();
  const updateMutation = useUpdateAnnouncement();
  const publishMutation = usePublishAnnouncement();
  const archiveMutation = useArchiveAnnouncement();
  const [selected, setSelected] = useState<Announcement | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [preview, setPreview] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const isSaving = createMutation.isPending || updateMutation.isPending;
  const isChangingStatus = publishMutation.isPending || archiveMutation.isPending;
  const mutationError = createMutation.error ?? updateMutation.error ?? publishMutation.error ?? archiveMutation.error;
  const list = announcements.data?.items;
  const selectedId = selected?.id;
  const sortedList = [...(list ?? [])].sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  );

  if (access.isLoading) {
    return <div className="announcement-admin-page announcement-admin-page--center"><Loader2 className="spin" size={24} /> 正在检查公告管理权限…</div>;
  }

  if (access.isError || !canManage) {
    return (
      <div className="announcement-admin-page announcement-admin-page--center">
        <div className="empty-state">
          <Bell size={32} />
          <h1>暂无公告管理权限</h1>
          <p>{access.isError ? errorMessage(access.error) : "只有活跃工作区的所有者或管理员可以管理全站公告。"}</p>
        </div>
      </div>
    );
  }

  const updateField = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setNotice(null);
    setForm((current) => ({ ...current, [key]: value }));
  };

  const startNew = () => {
    setSelected(null);
    setForm({ ...EMPTY_FORM });
    setPreview(false);
    setNotice(null);
  };

  const buildBody = () => ({
    title: form.title.trim(),
    summary: form.summary.trim() || null,
    content: form.content.trim(),
    kind: form.kind,
    link_url: form.link_url.trim() || null,
    starts_at: toIso(form.starts_at),
    ends_at: toIso(form.ends_at),
    is_pinned: form.is_pinned,
  });

  const save = async () => {
    setNotice(null);
    try {
      if (selectedId) {
        const result = await updateMutation.mutateAsync({ id: selectedId, ...buildBody() });
        setSelected(result);
        setForm(formFromAnnouncement(result));
        setNotice("公告已保存为当前状态。");
      } else {
        const result = await createMutation.mutateAsync(buildBody());
        setSelected(result);
        setForm(formFromAnnouncement(result));
        setNotice("公告已保存为草稿。");
      }
    } catch {
      // The mutation error is rendered below the form.
    }
  };

  const publish = async () => {
    try {
      const saved = selectedId
        ? await updateMutation.mutateAsync({ id: selectedId, ...buildBody() })
        : await createMutation.mutateAsync(buildBody());
      const result = await publishMutation.mutateAsync(saved.id);
      setSelected(result);
      setForm(formFromAnnouncement(result));
      setNotice("公告已发布，符合时间窗口后会显示在全站公告栏。");
    } catch {
      // The mutation error is rendered below the form.
    }
  };

  const archive = async () => {
    if (!selectedId) return;
    try {
      const result = await archiveMutation.mutateAsync(selectedId);
      setSelected(result);
      setNotice("公告已归档，不会再出现在公共公告栏。");
    } catch {
      // The mutation error is rendered below the form.
    }
  };

  return (
    <div className="announcement-admin-page">
      <header className="announcement-admin-header">
        <div>
          <span className="page-eyebrow"><Megaphone size={15} /> 运营工具</span>
          <h1>公告栏</h1>
          <p>发布产品更新、重要提醒与维护通知，保存后无需重新部署网站。</p>
        </div>
        <button type="button" className="button primary" onClick={startNew}><Plus size={17} /> 新建公告</button>
      </header>

      <div className="announcement-admin-layout">
        <section className="announcement-admin-list panel-card">
          <div className="announcement-admin-list__header">
            <div>
              <h2>公告列表</h2>
              <span>{sortedList.length} 条记录</span>
            </div>
            <button type="button" className="icon-button" onClick={() => announcements.refetch()} aria-label="刷新公告列表" title="刷新"><RefreshCw size={16} /></button>
          </div>
          <div className="announcement-filter-tabs" role="tablist" aria-label="公告状态筛选">
            {(Object.keys(statusLabels) as AnnouncementFilter[]).map((key) => (
              <button key={key} type="button" role="tab" aria-selected={filter === key} className={filter === key ? "active" : ""} onClick={() => onFilterChange(key)}>{statusLabels[key]}</button>
            ))}
          </div>
          {announcements.isLoading ? <div className="announcement-admin-list__empty"><Loader2 className="spin" size={20} /> 正在加载…</div> : null}
          {announcements.isError ? <div className="form-error">{errorMessage(announcements.error)}</div> : null}
          {!announcements.isLoading && sortedList.length === 0 ? (
            <div className="announcement-admin-list__empty"><FilePlus2 size={24} /><span>还没有{filter === "all" ? "公告" : statusLabels[filter]}，点击右上角开始创建。</span></div>
          ) : (
            <div className="announcement-list-items">
              {sortedList.map((item) => (
                <button key={item.id} type="button" className={`announcement-list-item ${selectedId === item.id ? "active" : ""}`} onClick={() => { setSelected(item); setForm(formFromAnnouncement(item)); setPreview(false); }}>
                  <span className={`announcement-list-item__dot announcement-list-item__dot--${item.kind}`} />
                  <span className="announcement-list-item__body">
                    <strong>{item.title}</strong>
                    <small>{statusLabels[item.status]} · {formatDate(item.updated_at)}</small>
                  </span>
                  {item.is_pinned && <Pin size={14} aria-label="置顶" />}
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="announcement-admin-editor panel-card">
          <div className="announcement-admin-editor__header">
            <div>
              <span className="page-eyebrow"><Pencil size={14} /> 编辑器</span>
              <h2>{selected ? "编辑公告" : "创建公告"}</h2>
            </div>
            <button type="button" className="button secondary" onClick={() => setPreview((value) => !value)}><Eye size={16} /> {preview ? "返回编辑" : "预览"}</button>
          </div>

          {preview ? (
            <div className={`announcement-preview announcement-preview--${form.kind}`}>
              <div className="announcement-preview__label">{kindLabels[form.kind]}</div>
              <h3>{form.title || "公告标题"}</h3>
              {form.summary && <p className="announcement-preview__summary">{form.summary}</p>}
              <div className="announcement-preview__content">{form.content || "公告正文将在这里显示。"}</div>
              {form.link_url && <a href={form.link_url} target="_blank" rel="noreferrer">打开相关链接</a>}
            </div>
          ) : (
            <div className="announcement-admin-form">
              <label><span>标题 <em>*</em></span><input value={form.title} onChange={(event) => updateField("title", event.target.value)} maxLength={160} placeholder="例如：新功能上线通知" /></label>
              <label><span>摘要</span><input value={form.summary} onChange={(event) => updateField("summary", event.target.value)} maxLength={320} placeholder="在公告栏中显示的一句话摘要" /></label>
              <label><span>正文 <em>*</em></span><textarea value={form.content} onChange={(event) => updateField("content", event.target.value)} maxLength={20_000} rows={9} placeholder="支持纯文本换行，不需要填写 HTML。" /></label>
              <div className="announcement-form-grid">
                <label><span>公告类型</span><select value={form.kind} onChange={(event) => updateField("kind", event.target.value as AnnouncementKind)}>{(Object.keys(kindLabels) as AnnouncementKind[]).map((key) => <option key={key} value={key}>{kindLabels[key]}</option>)}</select></label>
                <label><span>相关链接</span><input type="url" value={form.link_url} onChange={(event) => updateField("link_url", event.target.value)} placeholder="可选，以 https:// 开头" /></label>
                <label><span>开始显示时间</span><input type="datetime-local" value={form.starts_at} onChange={(event) => updateField("starts_at", event.target.value)} /></label>
                <label><span>结束显示时间</span><input type="datetime-local" value={form.ends_at} onChange={(event) => updateField("ends_at", event.target.value)} /></label>
              </div>
              <label className="announcement-checkbox"><input type="checkbox" checked={form.is_pinned} onChange={(event) => updateField("is_pinned", event.target.checked)} /><span><strong>置顶公告</strong><small>在有效公告中优先显示</small></span></label>
              {notice && <div className="form-success"><Check size={16} /> {notice}</div>}
              {mutationError && <div className="form-error">{errorMessage(mutationError)}</div>}
              <div className="announcement-form-actions">
                <button type="button" className="button primary" onClick={save} disabled={isSaving}>{isSaving ? <Loader2 className="spin" size={16} /> : <Check size={16} />} 保存草稿</button>
                {selected && selected.status !== "published" && <button type="button" className="button success" onClick={publish} disabled={isSaving || isChangingStatus}><Send size={16} /> 发布</button>}
                {selected && selected.status !== "archived" && <button type="button" className="button danger-ghost" onClick={archive} disabled={isSaving || isChangingStatus}><Archive size={16} /> 归档</button>}
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
