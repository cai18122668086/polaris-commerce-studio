import { isLocalDevelopmentAuthEnabled, LOCAL_DEV_AUTH_USER_ID } from "@/lib/auth/local-dev";

export type AdminAccess = { can_manage: boolean };

export type AdminAccount = {
  id: string;
  workspace_id: string;
  label: string;
  status: "active" | "paused" | "disabled";
  login_state: "unknown" | "ready" | "needs_login";
  last_login_at: string | null;
  last_used_at: string | null;
  profile_busy: boolean;
  active_lease_task_id: string | null;
  needs_relogin: boolean;
};

export type AdminOperationalAccount = AdminAccount & {
  lease_state: "active" | "expired" | "none";
  last_lease: {
    task_id: string;
    fencing_token: number;
    acquired_at: string | null;
    heartbeat_at: string | null;
    expires_at: string | null;
  } | null;
  platform: string;
  workspace_name: string | null;
  task_count: number;
  failed_task_count: number;
  risk_control_count: number;
  recent_tasks: Array<{
    id: string;
    platform: string;
    status: string;
    stage: string | null;
    progress: number;
    error_code: string | null;
    error_message: string | null;
    created_at: string | null;
    finished_at: string | null;
  }>;
  active_lease: {
    task_id: string;
    fencing_token: number;
    acquired_at: string | null;
    heartbeat_at: string | null;
    expires_at: string | null;
  } | null;
};

export type AdminPlatformOverview = {
  account_count: number;
  active_count: number;
  ready_count: number;
  needs_relogin_count: number;
  busy_count: number;
  accounts: AdminAccount[];
};

export type AdminOverview = {
  users: { total: number; active: number; disabled: number; recent_signups: number };
  workspaces: { total: number; active: number };
  usage: {
    jobs_total: number;
    jobs_running: number;
    jobs_failed: number;
    jobs_completed: number;
    crawl_tasks_total: number;
    crawl_tasks_running: number;
    crawl_tasks_failed: number;
    crawl_tasks_succeeded: number;
  };
  crawler_sessions: Record<string, AdminPlatformOverview>;
  generated_at: string;
};

export type AdminPagination = {
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
};

export type AdminUser = {
  id: string;
  display_name: string;
  email: string | null;
  status: string;
  last_login_at: string | null;
  created_at: string | null;
  last_activity_at: string | null;
  workspace_count: number;
  active_workspace_count: number;
  workspace_jobs_total: number;
  workspace_jobs_running: number;
  workspace_jobs_failed: number;
  crawl_tasks_total: number;
  crawl_tasks_running: number;
  crawl_tasks_failed: number;
};

export type AdminLog = {
  kind: "generation" | "crawl";
  id: string;
  workspace_id: string;
  workspace_name: string | null;
  type: string;
  platform: string | null;
  status: string;
  stage: string | null;
  progress: number;
  error_code: string | null;
  error_message: string | null;
  attempt_count: number;
  created_at: string | null;
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  event_count: number;
};

export type AdminLogEvent = {
  id: string;
  event_type: string;
  from_status: string | null;
  to_status: string | null;
  message: string;
  occurred_at: string | null;
};

export type AdminLogDetail = AdminLog & {
  events: AdminLogEvent[];
};

export type AdminWorkspace = {
  id: string;
  name: string;
  status: string;
  created_at: string | null;
  updated_at: string | null;
  last_activity_at: string | null;
  member_count: number;
  active_member_count: number;
  jobs_total: number;
  jobs_running: number;
  jobs_failed: number;
  crawl_tasks_total: number;
  crawl_tasks_running: number;
  crawl_tasks_failed: number;
  account_count: number;
  active_account_count: number;
  needs_relogin_count: number;
};

type AdminListResponse<T> = {
  items: T[];
  pagination: AdminPagination;
};

function requestHeaders() {
  const headers = new Headers({ Accept: "application/json" });
  if (isLocalDevelopmentAuthEnabled()) {
    headers.set("X-User-Id", LOCAL_DEV_AUTH_USER_ID);
  }
  return headers;
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(
      response.status === 401 || response.status === 403
        ? "暂无管理员工作台权限，请使用公告管理工作台相同的管理员身份登录。"
        : "管理员工作台暂时无法加载，请稍后重试。",
    );
  }
  const payload = await response.json() as { data: T } | T;
  return typeof payload === "object" && payload !== null && "data" in payload
    ? payload.data as T
    : payload as T;
}

function listQuery(params: { limit?: number; offset?: number; status?: string; search?: string }) {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  if (params.status) query.set("status", params.status);
  if (params.search) query.set("search", params.search);
  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

export async function getAdminAccess(signal?: AbortSignal): Promise<AdminAccess> {
  const response = await fetch("/api/v1/admin/overview/access", {
    credentials: "include",
    headers: requestHeaders(),
    signal,
  });
  return parseResponse<AdminAccess>(response);
}

export async function getAdminOverview(signal?: AbortSignal): Promise<AdminOverview> {
  const response = await fetch("/api/v1/admin/overview", {
    credentials: "include",
    cache: "no-store",
    headers: requestHeaders(),
    signal,
  });
  return parseResponse<AdminOverview>(response);
}

export async function getAdminUsers(
  params: { limit?: number; offset?: number; status?: string; search?: string } = {},
  signal?: AbortSignal,
): Promise<AdminListResponse<AdminUser>> {
  const response = await fetch(`/api/v1/admin/users${listQuery(params)}`, {
    credentials: "include",
    cache: "no-store",
    headers: requestHeaders(),
    signal,
  });
  return parseResponse<AdminListResponse<AdminUser>>(response);
}

export async function getAdminWorkspaces(
  params: { limit?: number; offset?: number; status?: string; search?: string } = {},
  signal?: AbortSignal,
): Promise<AdminListResponse<AdminWorkspace>> {
  const response = await fetch(`/api/v1/admin/workspaces${listQuery(params)}`, {
    credentials: "include",
    cache: "no-store",
    headers: requestHeaders(),
    signal,
  });
  return parseResponse<AdminListResponse<AdminWorkspace>>(response);
}
export async function getAdminLogs(
  params: {
    kind?: "all" | "generation" | "crawl";
    user_id?: string;
    workspace_id?: string;
    platform?: string;
    status?: string;
    created_from?: string;
    created_to?: string;
    limit?: number;
    offset?: number;
  } = {},
  signal?: AbortSignal,
): Promise<AdminListResponse<AdminLog>> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  const encoded = query.toString();
  const response = await fetch(`/api/v1/admin/logs${encoded ? `?${encoded}` : ""}`, {
    credentials: "include",
    cache: "no-store",
    headers: requestHeaders(),
    signal,
  });
  return parseResponse<AdminListResponse<AdminLog>>(response);
}


export async function getAdminLogDetail(
  kind: "generation" | "crawl",
  id: string,
  signal?: AbortSignal,
): Promise<AdminLogDetail> {
  const response = await fetch(`/api/v1/admin/logs/${kind}/${encodeURIComponent(id)}`, {
    credentials: "include",
    cache: "no-store",
    headers: requestHeaders(),
    signal,
  });
  return parseResponse<AdminLogDetail>(response);
}

export async function getAdminAccounts(
  params: {
    workspace_id?: string;
    platform?: string;
    status?: string;
    login_state?: string;
    needs_relogin?: boolean;
    limit?: number;
    offset?: number;
  } = {},
  signal?: AbortSignal,
): Promise<AdminListResponse<AdminOperationalAccount>> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  const encoded = query.toString();
  const response = await fetch(`/api/v1/admin/accounts${encoded ? `?${encoded}` : ""}`, {
    credentials: "include",
    cache: "no-store",
    headers: requestHeaders(),
    signal,
  });
  return parseResponse<AdminListResponse<AdminOperationalAccount>>(response);
}
