"use client";

import Link from "next/link";
import { ChevronDown, Grid2X2, Sparkles } from "lucide-react";
import { useState } from "react";
import type {
  NavigationFeatureGroup,
  NavigationMenuDefinition,
} from "@/lib/navigation-registry";

function FeatureLinks({
  groups,
  activeFeatureId,
  onNavigate,
}: {
  groups: readonly NavigationFeatureGroup[];
  activeFeatureId?: string;
  onNavigate: () => void;
}) {
  return groups.map((group, index) => (
    <section key={group.label} aria-labelledby={`navigation-group-${group.label}`}>
      <div
        className="nav-mega__head"
        style={index === 0 ? undefined : { marginTop: 10 }}
      >
        <span id={`navigation-group-${group.label}`}>
          {index === 0 ? <Sparkles size={14} /> : <Grid2X2 size={14} />}
          {group.label}
        </span>
      </div>
      <div className="nav-mega__grid">
        {group.items.map((item) => {
          const Icon = item.icon;
          const active = item.featureId === activeFeatureId;
          return (
            <Link
              key={item.featureId}
              href={item.href}
              className={`nav-tool-link${active ? " is-active" : ""}`}
              aria-current={active ? "page" : undefined}
              onClick={onNavigate}
            >
              <span className={`tool-icon ${item.tone}`} aria-hidden="true">
                <Icon size={19} />
              </span>
              <span>
                <strong>{item.label}</strong>
                <small>{item.description}</small>
              </span>
            </Link>
          );
        })}
      </div>
    </section>
  ));
}

export function NavigationMegaMenu({
  definition,
  activeFeatureId,
  active,
  open,
  onClose,
  onToggle,
}: {
  definition: NavigationMenuDefinition;
  activeFeatureId?: string;
  active: boolean;
  open: boolean;
  onClose: () => void;
  onToggle: () => void;
}) {
  const menuId = `navigation-menu-${definition.key}`;

  return (
    <div
      className={`nav-menu${open ? " is-open" : ""}`}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          onClose();
        }
      }}
    >
      <div className={`nav-menu__trigger ${active ? "active" : ""}`}>
        <Link
          href={definition.href}
          onClick={onClose}
          style={{ color: "inherit", whiteSpace: "nowrap" }}
        >
          {definition.label}
        </Link>
        <button
          type="button"
          onClick={onToggle}
          aria-label={`展开${definition.label}`}
          aria-controls={menuId}
          aria-expanded={open}
          style={{
            display: "inline-grid",
            width: 24,
            height: 30,
            placeItems: "center",
            padding: 0,
            border: 0,
            color: "inherit",
            background: "transparent",
          }}
        >
          <ChevronDown
            size={14}
            style={{ transform: open ? "rotate(180deg)" : undefined }}
          />
        </button>
      </div>
      <div id={menuId} className="nav-mega" aria-hidden={!open}>
        <FeatureLinks
          groups={definition.groups}
          activeFeatureId={activeFeatureId}
          onNavigate={onClose}
        />
        {definition.footer && (
          <div className="nav-mega__footer">
            <Link href={definition.footer.href} onClick={onClose}>
              {definition.footer.label}
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}

export function MobileNavigationMenu({
  open,
  menus,
  onClose,
  panelRef,
  primaryLinks,
  pathname,
}: {
  open: boolean;
  menus: readonly NavigationMenuDefinition[];
  onClose: () => void;
  panelRef: React.RefObject<HTMLDivElement | null>;
  primaryLinks: readonly { label: string; href: string }[];
  pathname: string;
}) {
  const [expandedMenu, setExpandedMenu] = useState<NavigationMenuDefinition["key"] | null>(
    "all-features",
  );

  if (!open) {
    return null;
  }

  return (
    <div
      id="mobile-primary-navigation"
      ref={panelRef}
      role="dialog"
      aria-label="移动端导航"
      style={{
        position: "absolute",
        zIndex: 100,
        top: "calc(100% - 4px)",
        right: 8,
        width: "min(92vw, 430px)",
        maxHeight: "calc(100vh - 72px)",
        overflowY: "auto",
        padding: 14,
        border: "1px solid #e4e7ee",
        borderRadius: "0 0 16px 16px",
        color: "#151827",
        background: "#fff",
        boxShadow: "0 24px 50px rgb(10 20 38 / 22%)",
      }}
    >
      <div style={{ display: "grid", gap: 8 }}>
        <nav
          aria-label="移动端主导航链接"
          style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 7 }}
        >
          {primaryLinks.map((item) => {
            const active =
              item.href === "/"
                ? pathname === "/"
                : pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onClose}
                aria-current={active ? "page" : undefined}
                style={{
                  padding: "10px 7px",
                  border: `1px solid ${active ? "#cfc4ff" : "#eceef3"}`,
                  borderRadius: 9,
                  color: active ? "#5d42c7" : "#343846",
                  background: active ? "#f4f0ff" : "#fafbfc",
                  textAlign: "center",
                  fontSize: 12,
                  fontWeight: 700,
                }}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        {menus.map((menu) => {
          const expanded = expandedMenu === menu.key;
          const sectionId = `mobile-navigation-${menu.key}`;
          return (
            <section
              key={menu.key}
              style={{ border: "1px solid #eceef3", borderRadius: 12, overflow: "hidden" }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  minHeight: 46,
                  paddingLeft: 13,
                  background: expanded ? "#f6f7fb" : "#fff",
                }}
              >
                <Link
                  href={menu.href}
                  onClick={onClose}
                  style={{ flex: 1, color: "#171a27", fontSize: 14, fontWeight: 700 }}
                >
                  {menu.label}
                </Link>
                <button
                  type="button"
                  onClick={() => setExpandedMenu(expanded ? null : menu.key)}
                  aria-label={`${expanded ? "收起" : "展开"}${menu.label}`}
                  aria-controls={sectionId}
                  aria-expanded={expanded}
                  style={{
                    display: "inline-grid",
                    width: 46,
                    alignSelf: "stretch",
                    placeItems: "center",
                    border: 0,
                    color: "#596173",
                    background: "transparent",
                  }}
                >
                  <ChevronDown
                    size={16}
                    style={{ transform: expanded ? "rotate(180deg)" : undefined }}
                  />
                </button>
              </div>
              {expanded && (
                <div
                  id={sectionId}
                  style={{ display: "grid", gap: 7, padding: 10, background: "#fff" }}
                >
                  {menu.groups.map((group) => (
                    <div key={group.label} style={{ display: "grid", gap: 6 }}>
                      <strong
                        style={{
                          padding: "4px 3px 1px",
                          color: "#7a8190",
                          fontSize: 11,
                        }}
                      >
                        {group.label}
                      </strong>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 6 }}>
                        {group.items.map((item) => {
                          const active =
                            pathname === item.href || pathname.startsWith(`${item.href}/`);
                          return (
                            <Link
                              key={item.featureId}
                              href={item.href}
                              onClick={onClose}
                              aria-current={active ? "page" : undefined}
                              style={{
                                minWidth: 0,
                                padding: "10px 9px",
                                border: `1px solid ${active ? "#cfc4ff" : "#eceef3"}`,
                                borderRadius: 9,
                                color: active ? "#5d42c7" : "#252938",
                                background: active ? "#f4f0ff" : "#fafbfc",
                                fontSize: 12,
                                fontWeight: 650,
                              }}
                            >
                              {item.label}
                            </Link>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                  {menu.footer && (
                    <Link
                      href={menu.footer.href}
                      onClick={onClose}
                      style={{ padding: "7px 3px 2px", color: "#5d42c7", fontSize: 12, fontWeight: 700 }}
                    >
                      {menu.footer.label}
                    </Link>
                  )}
                </div>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
