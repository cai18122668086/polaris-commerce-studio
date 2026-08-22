import Link from "next/link";
import { ChevronLeft, Plus } from "lucide-react";

export function WorkspaceHeader({
  eyebrow,
  title,
  description,
  meta,
}: {
  eyebrow: string;
  title: string;
  description: string;
  meta?: React.ReactNode;
}) {
  function startNewTask() {
    if (typeof window !== "undefined") {
      window.location.replace(window.location.pathname);
    }
  }

  return (
    <div className="workspace-header">
      <div>
        <Link href="/" className="back-link">
          <ChevronLeft size={15} />
          工作台
        </Link>
        <p>{eyebrow}</p>
        <h1>{title}</h1>
        <span>{description}</span>
      </div>
      <div className="workspace-header__actions">
        {meta}
        <button type="button" className="secondary-button" onClick={startNewTask}>
          <Plus size={16} />
          新建任务
        </button>
      </div>
    </div>
  );
}

