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
  queued: { label: "排队中", className: "status-queued", icon: Clock3 },
  planning: { label: "正在规划", className: "status-planning", icon: LoaderCircle },
  awaiting_confirmation: { label: "等待确认", className: "status-warning", icon: Clock3 },
  processing: { label: "正在生成", className: "status-processing", icon: LoaderCircle },
  cancelling: { label: "取消中", className: "status-neutral", icon: LoaderCircle },
  partial: { label: "部分完成", className: "status-warning", icon: TriangleAlert },
  completed: { label: "已完成", className: "status-success", icon: CheckCircle2 },
  failed: { label: "生成失败", className: "status-danger", icon: TriangleAlert },
  cancelled: { label: "已取消", className: "status-neutral", icon: Ban },
};

export function StatusBadge({ status, stage }: { status: JobStatus; stage?: string | null }) {
  const auditLabels: Record<string, string> = {
    set_auditing: "整组审核中",
    set_audit_error: "审核异常待确认",
    set_audit_failed: "整组审核未通过",
  };
  const config = statusMap[status];
  const Icon = config.icon;

  return (
    <span className={`status-badge ${config.className}`}>
      <Icon size={13} className={["processing", "planning", "cancelling"].includes(status) ? "spin" : ""} />
      {(stage && auditLabels[stage]) || config.label}
    </span>
  );
}

