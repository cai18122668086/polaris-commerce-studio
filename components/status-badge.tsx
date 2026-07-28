import {
  Ban,
  CheckCircle2,
  CircleDashed,
  Clock3,
  LoaderCircle,
  TriangleAlert,
} from "lucide-react";
import type { JobStatus } from "@/lib/api/types";

const statusMap: Record<
  JobStatus,
  { label: string; className: string; icon: typeof Clock3 }
> = {
  draft: { label: "草稿", className: "status-neutral", icon: CircleDashed },
  queued: { label: "等待中", className: "status-queued", icon: Clock3 },
  planning: { label: "规划中", className: "status-planning", icon: LoaderCircle },
  awaiting_confirmation: { label: "待确认计划", className: "status-warning", icon: Clock3 },
  processing: { label: "生成中", className: "status-processing", icon: LoaderCircle },
  cancelling: { label: "取消中", className: "status-neutral", icon: LoaderCircle },
  partial: { label: "部分成功", className: "status-warning", icon: TriangleAlert },
  completed: { label: "已完成", className: "status-success", icon: CheckCircle2 },
  failed: { label: "失败", className: "status-danger", icon: TriangleAlert },
  cancelled: { label: "已取消", className: "status-neutral", icon: Ban },
};

export function StatusBadge({ status }: { status: JobStatus }) {
  const config = statusMap[status];
  const Icon = config.icon;

  return (
    <span className={`status-badge ${config.className}`}>
      <Icon size={13} className={["processing", "planning", "cancelling"].includes(status) ? "spin" : ""} />
      {config.label}
    </span>
  );
}

