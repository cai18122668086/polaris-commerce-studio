export type ReplicaMethod = "style" | "exact";
export const REPLICA_MODE_VERSION = "replica-modes-v2";
export const DEFAULT_REPLICA_METHOD: ReplicaMethod = "style";
export const REPLICA_MODE_CHOICES = [
  { value: "style", label: "风格模仿", description: "约 5 分钟 · 功能强大", price: 8, recommended: true },
  { value: "exact", label: "一比一复刻", description: "约 40 分钟 · 一模一样", price: 15 },
] as const;

export function replicaSpeedFor(method: ReplicaMethod): "fast" | "standard" {
  return method === "style" ? "fast" : "standard";
}

export function replicaCreditsFor(method: ReplicaMethod): number {
  return method === "style" ? 8 : 15;
}

export function replicaDraftMethod(saved: { replicaModeVersion?: string; replicationMethod?: string }): ReplicaMethod {
  // Unsubmitted drafts from the former modes start with the new recommendation.
  return saved.replicaModeVersion === REPLICA_MODE_VERSION && saved.replicationMethod === "exact" ? "exact" : DEFAULT_REPLICA_METHOD;
}
