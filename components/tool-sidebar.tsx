"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight, Plus, X } from "lucide-react";
import { futureTools, toolGroups } from "@/lib/tool-registry";

export function ToolSidebar({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const pathname = usePathname();

  return (
    <>
      {open && <button className="mobile-overlay" onClick={onClose} aria-label="关闭菜单" />}
      <aside className={`tool-sidebar ${open ? "mobile-open" : ""}`}>
        <div className="sidebar-mobile-head">
          <strong>功能导航</strong>
          <button className="icon-button" onClick={onClose} aria-label="关闭菜单">
            <X size={18} />
          </button>
        </div>
        <Link href="/workspace/local-edit" className="new-task-button" onClick={onClose}>
          <Plus size={17} />
          新建创作
        </Link>
        <div className="tool-groups">
          {toolGroups.map((group) => (
            <section key={group.label} className="tool-group">
              <p>{group.label}</p>
              {group.items.map((item) => {
                const active = pathname === item.href;
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`tool-link ${active ? "active" : ""}`}
                    onClick={onClose}
                  >
                    <span className={`tool-icon tone-${item.tone}`}>
                      <Icon size={18} />
                    </span>
                    <span>
                      <strong>{item.title}</strong>
                      <small>{item.description}</small>
                    </span>
                    {item.badge ? <em>{item.badge}</em> : <ChevronRight size={14} />}
                  </Link>
                );
              })}
            </section>
          ))}
        </div>
        <div className="future-tools">
          <p>即将上线</p>
          {futureTools.map((item) => {
            const Icon = item.icon;
            return (
              <span key={item.label}>
                <Icon size={15} />
                {item.label}
                <i>敬请期待</i>
              </span>
            );
          })}
        </div>
        <div className="sidebar-tip">
          <span>PRO</span>
          <strong>让创作流程更顺畅</strong>
          <p>本月已为你节省约 12.6 小时</p>
        </div>
      </aside>
    </>
  );
}

