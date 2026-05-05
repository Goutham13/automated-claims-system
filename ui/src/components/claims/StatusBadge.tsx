import { cn } from "@/lib/utils";
import type { ClaimStatus, StepStatus } from "@/lib/claims-types";

const CLAIM_LABELS: Record<ClaimStatus, string> = {
  PROCESSING: "Processing",
  WAITING_FOR_REUPLOAD: "Waiting for Reupload",
  BLOCKED: "Blocked",
  COMPLETED: "Completed",
  ERROR: "Error",
};

const STEP_LABELS: Record<StepStatus, string> = {
  COMPLETED: "Completed",
  BLOCKED: "Blocked",
  PENDING_REUPLOAD: "Pending Reupload",
  SKIPPED: "Skipped",
  IN_PROGRESS: "In Progress",
};

const tone = (status: ClaimStatus | StepStatus): string => {
  switch (status) {
    case "COMPLETED":
      return "bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-200 dark:border-emerald-900";
    case "BLOCKED":
    case "ERROR":
      return "bg-red-100 text-red-800 border-red-200 dark:bg-red-900/30 dark:text-red-200 dark:border-red-900";
    case "WAITING_FOR_REUPLOAD":
    case "PENDING_REUPLOAD":
      return "bg-amber-100 text-amber-900 border-amber-200 dark:bg-amber-900/30 dark:text-amber-200 dark:border-amber-900";
    case "SKIPPED":
      return "bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700";
    case "PROCESSING":
    case "IN_PROGRESS":
    default:
      return "bg-sky-100 text-sky-800 border-sky-200 dark:bg-sky-900/30 dark:text-sky-200 dark:border-sky-900";
  }
};

export function StatusBadge({
  status,
  kind = "claim",
  className,
}: {
  status: ClaimStatus | StepStatus;
  kind?: "claim" | "step";
  className?: string;
}) {
  const label =
    kind === "claim"
      ? CLAIM_LABELS[status as ClaimStatus] ?? status
      : STEP_LABELS[status as StepStatus] ?? status;
  const dot = (
    <span
      className={cn(
        "mr-1.5 inline-block h-1.5 w-1.5 rounded-full",
        status === "COMPLETED" && "bg-emerald-500",
        (status === "BLOCKED" || status === "ERROR") && "bg-red-500",
        (status === "WAITING_FOR_REUPLOAD" || status === "PENDING_REUPLOAD") && "bg-amber-500",
        status === "SKIPPED" && "bg-slate-400",
        (status === "PROCESSING" || status === "IN_PROGRESS") && "bg-sky-500 animate-pulse",
      )}
    />
  );
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium",
        tone(status),
        className,
      )}
    >
      {dot}
      {label}
    </span>
  );
}
