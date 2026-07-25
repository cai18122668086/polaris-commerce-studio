import {
  Ban,
  CheckCircle2,
  CircleDashed,
  Clock3,
  LoaderCircle,
  TriangleAlert,
} from "lucide-react";
import type { JobStatus } from "@/lib/mock-data";

const statusMap: Record<
  JobStatus,
  { label: string; className: string; icon: typeof Clock3 }
> = {
  draft: { label: "草稿", className: "status-neutral", icon: CircleDashed },
  queued: { label: "等待中", className: "status-queued", icon: Clock3 },
  planning: { label: "规划中", className: "status-planning", icon: LoaderCircle },
  processing: { label: "生成中", className: "status-processing", icon: LoaderCircle },
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
      <Icon size={13} className={status === "processing" || status === "planning" ? "spin" : ""} />
      {config.label}
    </span>
  );
}

