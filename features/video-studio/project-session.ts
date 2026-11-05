import { emptyVideoContent, type VideoContent, type VideoProject, type VideoProjectApi, type VideoTask, type VideoVersion, type VideoWrite, type VideoWriteResult } from "./projects";

type Recovery = { projectId: string; revision: number; content: VideoContent; pending?: VideoWrite; importRequest?: Parameters<VideoProjectApi["importLegacy"]>[0] };
export type ProjectSessionState = {
  content: VideoContent; projectId: string; revision: number; projects: VideoProject[];
  copies: VideoVersion[]; tasks: VideoTask[]; history: VideoVersion[];
  status: "loading" | "saved" | "dirty" | "saving" | "error" | "conflict";
  error?: string; recovery?: Recovery; legacyAvailable: boolean;
  backupUnavailable?: boolean;
};

// One serial writer per editor. Never replace newer edits with an old response,
// and retry an unknown result with the exact same idempotency key + payload.
export class VideoProjectSession {
  state: ProjectSessionState = { content: emptyVideoContent(), projectId: "", revision: 0, projects: [], copies: [], tasks: [], history: [], status: "loading", legacyAvailable: false };
  private listeners = new Set<() => void>();
  private pending?: VideoWrite;
  private importing?: Recovery["importRequest"];
  private saved = "";
  private needsHistory = false;
  private queue: Promise<unknown> = Promise.resolve();
  private actionFlight?: { action: VideoWrite["action"]; promise: Promise<VideoWriteResult | undefined> };
  private timer?: ReturnType<typeof setTimeout>;
  private disposed = false;
  constructor(private api: VideoProjectApi, private storage: Pick<Storage, "getItem" | "setItem" | "removeItem">, readonly recoveryKey: string) {}
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  getSnapshot = () => this.state;
  private publish(patch: Partial<ProjectSessionState>) {
    if (this.disposed) return;
    this.state = { ...this.state, ...patch };
    this.listeners.forEach(listener => listener());
  }
  private checkpoint() {
    if (this.disposed) return;
    try { this.storage.setItem(this.recoveryKey, JSON.stringify({ projectId: this.state.projectId, revision: this.state.revision, content: this.state.content, pending: this.pending, importRequest: this.importing })); }
    catch { this.publish({ backupUnavailable: true }); }
  }
  private readLocal(key: string) { try { return this.storage.getItem(key); } catch { return null; } }
  private removeLocal(key: string) { try { this.storage.removeItem(key); } catch { /* Server saving does not require local storage. */ } }
  private async legacyRequestId(raw: string) {
    const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`video-legacy-v1:${raw}`));
    const hex = Array.from(new Uint8Array(hash), n => n.toString(16).padStart(2, "0")).join("").slice(0, 32);
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  async initialize(preferredId?: string) {
    this.disposed = false;
    this.publish({ status: "loading", error: undefined });
    try {
      let recovery: Recovery | undefined;
      try {
        const value = JSON.parse(this.readLocal(this.recoveryKey) || "null");
        if (value?.content?.draft && typeof value.projectId === "string" && typeof value.revision === "number") recovery = value;
      } catch { /* A broken recovery file cannot replace server data. */ }
      const [projects, copies, tasks] = await Promise.all([this.api.projects(), this.api.versions(), this.api.tasks()]);
      const id = preferredId || recovery?.projectId || projects[0]?.id;
      let project = projects.find(item => item.id === id);
      if (id && !project) {
        try { project = await this.api.project(id); }
        catch (error) { if ((error as { status?: number }).status !== 404 || preferredId) throw error; }
      }
      const content = project?.content ?? emptyVideoContent();
      const legacy = this.readLocal("polaris-video-studio-demo-v1");
      const legacyAvailable = Boolean(legacy && await this.legacyRequestId(legacy) !== this.readLocal(`${this.recoveryKey}:legacy-imported`));
      if (this.disposed) return;
      this.pending = undefined;
      this.saved = JSON.stringify(content);
      this.publish({ projects: project && !projects.some(p => p.id === project.id) ? [project, ...projects] : projects, copies, tasks, content, projectId: project?.id || id || crypto.randomUUID(), revision: project?.revision || 0, status: "saved", recovery, legacyAvailable });
      this.needsHistory = true;
      await this.loadHistory();
      this.needsHistory = false;
    } catch (error) { this.fail(error); }
  }
  edit(content: VideoContent) {
    if (this.state.status === "loading" || this.state.recovery || this.importing || !this.state.projectId) return;
    this.publish({ content, status: this.state.status === "conflict" ? "conflict" : this.state.status === "error" ? "error" : "dirty" });
    this.checkpoint();
    clearTimeout(this.timer);
    if (!this.state.error && this.state.status !== "conflict") this.timer = setTimeout(() => { void this.save().catch(() => undefined); }, 650);
  }
  private fail(error: unknown) {
    const conflict = (error as { status?: number }).status === 409;
    this.publish({ status: conflict ? "conflict" : "error", error: conflict ? "另一设备已更新，当前内容已保留在本机。请另存项目或重新载入。" : "暂时无法确认同步结果，当前内容保留在本机，请重试。" });
  }
  save(action: VideoWrite["action"] = "save"): Promise<VideoWriteResult | undefined> {
    if (action !== "save" && this.actionFlight?.action === action) return this.actionFlight.promise;
    clearTimeout(this.timer);
    const operation = this.queue.catch(() => undefined).then(async () => {
      if (this.disposed || !this.state.projectId || this.state.status === "loading") return;
      if (this.state.recovery) throw new Error("请先处理本机未保存内容。");
      this.publish({ status: "saving", error: undefined });
      try {
        if (this.importing) {
          const response = await this.api.importLegacy(this.importing);
          if (this.disposed) return response;
          try { this.storage.setItem(`${this.recoveryKey}:legacy-imported`, this.importing.request_id); } catch { /* Stable server idempotency still prevents duplicate imports. */ }
          this.importing = undefined;
          this.needsHistory = true;
          this.pending = undefined;
          this.saved = JSON.stringify(response.project.content);
          this.publish({ content: response.project.content, projectId: response.project.id, revision: response.project.revision, legacyAvailable: false, projects: [response.project, ...this.state.projects.filter(p => p.id !== response.project.id)] });
        }
        let response: VideoWriteResult | undefined;
        // A pending action is already a user request; retries never submit it twice.
        const nextAction = this.pending?.action === action ? "save" : action;
        if (this.pending) response = await this.commit(this.pending);
        if (this.disposed) return response;
        if (nextAction !== "save" || JSON.stringify(this.state.content) !== this.saved) {
          this.pending = { request_id: crypto.randomUUID(), expected_revision: this.state.revision, content: structuredClone(this.state.content), action: nextAction };
          this.checkpoint();
          response = await this.commit(this.pending);
        }
        if (this.disposed) return response;
        if (this.needsHistory) { await this.refreshHistory(); this.needsHistory = false; }
        const dirty = JSON.stringify(this.state.content) !== this.saved;
        this.publish({ status: dirty ? "dirty" : "saved" });
        if (dirty) this.checkpoint(); else this.removeLocal(this.recoveryKey);
        return response;
      } catch (error) { this.checkpoint(); this.fail(error); throw error; }
    });
    this.queue = operation;
    if (action !== "save") {
      this.actionFlight = { action, promise: operation };
      const clear = () => { if (this.actionFlight?.promise === operation) this.actionFlight = undefined; };
      void operation.then(clear, clear);
    }
    return operation;
  }
  private async commit(body: VideoWrite) {
    const response = await this.api.write(this.state.projectId, body);
    if (this.disposed) return response;
    this.pending = undefined;
    if (response.version || response.task) this.needsHistory = true;
    this.saved = JSON.stringify(body.content);
    this.publish({ revision: response.project.revision, projects: [response.project, ...this.state.projects.filter(p => p.id !== response.project.id)] });
    return response;
  }
  async refreshHistory() {
    const [copies, tasks] = await Promise.all([this.api.versions(), this.api.tasks()]);
    this.publish({ copies, tasks });
    await this.loadHistory();
  }
  async loadHistory() {
    if (!this.state.revision) { this.publish({ history: [] }); return; }
    const [drafts, confirmed] = await Promise.all([this.api.versions(this.state.projectId, "draft"), this.api.versions(this.state.projectId, "confirmed")]);
    this.publish({ history: [...drafts, ...confirmed].sort((a, b) => b.created_at.localeCompare(a.created_at)) });
  }
  async select(id: string) { await this.save(); await this.initialize(id); }
  async newProject() {
    await this.save();
    this.saved = JSON.stringify(emptyVideoContent());
    this.publish({ projectId: crypto.randomUUID(), revision: 0, content: emptyVideoContent(), history: [], status: "saved" });
  }
  async saveAsNew() {
    // Only a definite conflict permits abandoning the old request safely.
    if (this.state.status !== "conflict") return;
    this.pending = undefined;
    this.saved = "";
    this.publish({ projectId: crypto.randomUUID(), revision: 0, recovery: undefined, error: undefined });
    this.checkpoint();
    await this.save();
  }
  restoreRecovery() {
    const value = this.state.recovery;
    if (!value) return;
    this.pending = value.pending;
    this.importing = value.importRequest;
    this.publish({ content: value.content, projectId: value.projectId, revision: value.revision, recovery: undefined, error: undefined, status: "dirty" });
    this.saved = "";
    this.checkpoint();
    void this.save().catch(() => undefined);
  }
  async discardRecovery() { this.removeLocal(this.recoveryKey); this.pending = undefined; this.importing = undefined; await this.initialize(this.state.revision ? this.state.projectId : undefined); }
  async importLegacy() {
    await this.save();
    const raw = this.readLocal("polaris-video-studio-demo-v1") || "null";
    const legacy = JSON.parse(raw);
    if (!legacy?.draft) throw new Error("本机旧记录无法读取。");
    this.importing = { request_id: await this.legacyRequestId(raw), draft: legacy.draft, copies: legacy.copies || [], works: legacy.works || [] };
    this.checkpoint();
    await this.save();
    await this.refreshHistory();
    // The original unscoped demo key is preserved as a read-only backup.
    this.publish({ legacyAvailable: false });
  }
  dispose() { this.disposed = true; clearTimeout(this.timer); this.listeners.clear(); }
}
