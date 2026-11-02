"use client";

import type { AnchorHTMLAttributes } from "react";

/** Open saved tasks in a fresh document, including same-workspace links. */
export function TaskWorkspaceLink({ children, ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) {
  return <a {...props}>{children}</a>;
}

export function openTaskWorkspace(href: string) {
  window.location.assign(new URL(href, window.location.origin).href);
}

export function replaceTaskWorkspace(href: string) {
  window.location.replace(new URL(href, window.location.origin).href);
}
