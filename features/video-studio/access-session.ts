export type VideoGrantResult = { status: "allowed"; userId: string } | { status: "denied" | "revoked" };
export type VideoGrantState = { path: string; status: "checking" | "allowed" | "denied" | "revoked" | "error"; userId?: string; checking: boolean };
export const INITIAL_VIDEO_GRANT: VideoGrantState = { path: "", status: "checking", checking: false };

// Ephemeral state for one mounted consumer. Never persisted or reused across
// routes/accounts. A same-route focus check is not an authentication failure.
export class VideoAccessSession {
  private state: VideoGrantState = INITIAL_VIDEO_GRANT;
  private listeners = new Set<() => void>();
  private active?: { controller: AbortController; promise: Promise<void> };
  private revision = 0;

  constructor(private verify: (signal: AbortSignal) => Promise<VideoGrantResult>) {}
  snapshot = () => this.state;
  serverSnapshot = () => INITIAL_VIDEO_GRANT;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private publish(state: VideoGrantState) { this.state = state; this.listeners.forEach(listener => listener()); }

  cancel() { this.revision += 1; this.active?.controller.abort(); this.active = undefined; }
  setPath(path: string) {
    if (this.state.path === path) return;
    this.cancel(); this.publish({ path, status: "checking", checking: false });
  }
  revoke() {
    this.cancel(); this.publish({ path: this.state.path, status: "revoked", checking: false });
  }
  sessionChanged() {
    this.cancel(); this.publish({ path: this.state.path, status: "checking", checking: false });
  }
  check(): Promise<void> {
    if (this.active) return this.active.promise;
    const revision = ++this.revision;
    const controller = new AbortController();
    // Keep the same editor mounted during ordinary background validation.
    // Logout/session change and path change clear the identity separately.
    this.publish({ ...this.state, checking: true });
    const promise = Promise.resolve().then(() => this.verify(controller.signal)).then(result => {
      if (revision !== this.revision || controller.signal.aborted) return;
      this.publish(result.status === "allowed"
        ? { path: this.state.path, status: "allowed", userId: result.userId, checking: false }
        : { path: this.state.path, status: result.status, checking: false });
    }).catch(() => {
      if (revision !== this.revision || controller.signal.aborted) return;
      // A transient outage cannot revoke a known same-route identity or delete
      // a selected recording. All business APIs still enforce server-side auth.
      // An initial failure has no userId and cannot mount an editor at all.
      this.publish({ ...this.state, status: "error", checking: false });
    }).finally(() => {
      if (this.active?.controller === controller) this.active = undefined;
      controller.abort();
    });
    this.active = { controller, promise };
    return promise;
  }
}
