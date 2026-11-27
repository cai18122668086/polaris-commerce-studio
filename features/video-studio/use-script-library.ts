"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { LibraryEdit, LibraryEntry, LibraryPage, LibraryPlatform } from "./script-library-format";

/**
 * 文案库接口（/script-library）。写稿结果在服务器上自动入库，这里只负责读、改、删。
 * 列表可搜索、按平台筛选、分页；也可以按条目 id 或文稿 id 批量取。
 */

const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const api = apiClient as any;
export const LIBRARY_PAGE_SIZE = 20;

export function scriptLibraryApi(workspaceId: string) {
  const opts = (query?: Record<string, string | number>) => ({ params: { path: { workspace_id: workspaceId }, ...(query ? { query } : {}) }, signal: AbortSignal.timeout(15000), cache: "no-store" as const });
  const entry = (id: string) => ({ ...opts(), params: { path: { workspace_id: workspaceId, entry_id: id } } });
  return {
    list: async (query: { q?: string; platform?: LibraryPlatform | ""; limit?: number; offset?: number }) =>
      unwrapApiResponse(await api.GET(`${root}/script-library`, opts({ q: query.q || "", platform: query.platform || "", limit: query.limit || LIBRARY_PAGE_SIZE, offset: query.offset || 0 }))) as LibraryPage,
    byIds: async (ids: string[]) => ids.length ? unwrapApiResponse(await api.GET(`${root}/script-library`, opts({ ids: ids.join(",") }))) as LibraryPage : { items: [], total: 0, limit: 0, offset: 0, missing_ids: [] } as LibraryPage,
    byDocuments: async (ids: string[]) => ids.length ? unwrapApiResponse(await api.GET(`${root}/script-library`, opts({ documents: ids.join(",") }))) as LibraryPage : { items: [], total: 0, limit: 0, offset: 0, missing_ids: [] } as LibraryPage,
    get: async (id: string) => unwrapApiResponse(await api.GET(`${root}/script-library/{entry_id}`, entry(id))) as LibraryEntry,
    update: async (row: LibraryEntry, edit: LibraryEdit) => unwrapApiResponse(await api.PUT(`${root}/script-library/{entry_id}`, { ...entry(row.id), body: { expected_revision: row.revision, publish_title: edit.publish_title.trim(), publish_body: edit.publish_body.trim(), script: edit.script.trim(), platform: row.platform } })) as LibraryEntry,
    remove: async (id: string) => { unwrapApiResponse(await api.DELETE(`${root}/script-library/{entry_id}`, entry(id))); },
  };
}

const message = (caught: unknown, fallback: string) => caught instanceof Error && caught.message ? caught.message : fallback;

/** The library page: query, page, selection across pages, one open entry. */
export function useScriptLibrary(workspaceId: string) {
  const client = useRef(scriptLibraryApi(workspaceId));
  useEffect(() => { client.current = scriptLibraryApi(workspaceId); }, [workspaceId]);
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState<LibraryPlatform | "">("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<LibraryPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const latest = useRef(0);

  const reload = useCallback(async () => {
    const ticket = ++latest.current;
    setLoading(true);
    try {
      const next = await client.current.list({ q: query.trim(), platform, offset });
      if (ticket !== latest.current) return;
      if (!next.items.length && offset > 0 && next.total > 0) { setOffset(Math.max(0, offset - LIBRARY_PAGE_SIZE)); return; }
      setPage(next); setError("");
    } catch (caught) {
      if (ticket === latest.current) setError(message(caught, "文案库暂时读不到，请稍后重试。"));
    } finally {
      if (ticket === latest.current) setLoading(false);
    }
  }, [query, platform, offset]);

  useEffect(() => {
    const timer = setTimeout(() => { void reload(); }, query ? 250 : 0);
    return () => clearTimeout(timer);
  }, [reload, query]);

  const search = (value: string) => { setQuery(value); setOffset(0); };
  const filter = (value: LibraryPlatform | "") => { setPlatform(value); setOffset(0); };
  const save = async (row: LibraryEntry, edit: LibraryEdit) => {
    setBusy("save");
    try {
      const next = await client.current.update(row, edit);
      setPage(current => current && { ...current, items: current.items.map(item => item.id === next.id ? next : item) });
      return next;
    } finally { setBusy(""); }
  };
  const remove = async (id: string) => {
    setBusy("remove");
    try { await client.current.remove(id); await reload(); } finally { setBusy(""); }
  };
  return { query, platform, offset, page, loading, error, busy, search, filter, setOffset, reload, save, remove };
}
