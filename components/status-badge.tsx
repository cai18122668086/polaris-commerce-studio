import {
  Ban,
  CheckCircle2,
  CircleDashed,
  Clock3,
  LoaderCircle,
  TriangleAlert,
} from "lucide-react";
import type { Job, JobStatus } from "@/lib/api/types";
import { jobStatusLabel } from "@/lib/jobs/presentation";

const statusMap: Record<
  JobStatus,
  { label: string; className: string; icon: typeof Clock3 }
> = {
  draft: { label: "草稿", className: "status-neutral", icon: CircleDashed },
  queued: { label: "排队中", className: "status-queued", icon: Clock3 },
  planning: { label: "正在规划", className: "status-planning", icon: LoaderCircle },
  awaiting_confirmation: { label: "等待确认", className: "status-warning", icon: Clock3 },
  processing: { label: "正在生成", className: "status-processing", icon: LoaderCircle },
  awaiting_final_review: { label: "等待整组确认", className: "status-warning", icon: Clock3 },
  cancelling: { label: "取消中", className: "status-neutral", icon: LoaderCircle },
  partial: { label: "部分完成", className: "status-warning", icon: TriangleAlert },
  completed: { label: "已完成", className: "status-success", icon: CheckCircle2 },
  failed: { label: "生成失败", className: "status-danger", icon: TriangleAlert },
  cancelled: { label: "已取消", className: "status-neutral", icon: Ban },
};

/** Pass jobType so single-image jobs never read as a whole-set confirmation. */
export function StatusBadge({ status, jobType }: { status: JobStatus; jobType?: Job["type"] }) {
  const config = statusMap[status];
  const label = status === "awaiting_final_review" && jobType ? jobStatusLabel(status, jobType) : config.label;
  const Icon = config.icon;

  return (
    <span className={`status-badge ${config.className}`}>
      <Icon size={13} className={["processing", "planning", "cancelling"].includes(status) ? "spin" : ""} />
      {label}
    </span>
  );
}

