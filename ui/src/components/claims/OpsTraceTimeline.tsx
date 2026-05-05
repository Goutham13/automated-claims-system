import { AlertTriangle, AlertOctagon } from "lucide-react";
import type { ActiveClaimState } from "@/lib/claims-types";
import { TraceStepCard } from "./TraceStepCard";
import { JsonViewer } from "./JsonViewer";
import { Skeleton } from "@/components/ui/skeleton";

export function OpsTraceTimeline({ active }: { active: ActiveClaimState }) {
  const steps = active.stepOrder.map((k) => active.steps[k]).filter(Boolean);

  return (
    <div className="space-y-4">
      {steps.length === 0 && !active.error && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Skeleton className="h-3 w-3 rounded-full" />
            <Skeleton className="h-4 w-40" />
          </div>
          <Skeleton className="h-20 w-full rounded-md" />
          <Skeleton className="h-20 w-full rounded-md" />
        </div>
      )}

      {steps.length > 0 && (
        <div className="relative space-y-3 before:absolute before:left-3.5 before:top-2 before:bottom-2 before:w-px before:bg-border">
          {steps.map((s, i) => (
            <TraceStepCard key={s.key} step={s} index={i} />
          ))}
        </div>
      )}

      {active.blockers.length > 0 && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 dark:border-red-900 dark:bg-red-950/30">
          <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-red-800 dark:text-red-200">
            <AlertOctagon className="h-3.5 w-3.5" />
            Blockers
          </div>
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-red-800 dark:text-red-200">
            {active.blockers.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
        </div>
      )}

      {active.warnings.length > 0 && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 dark:border-amber-900 dark:bg-amber-950/30">
          <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-amber-900 dark:text-amber-200">
            <AlertTriangle className="h-3.5 w-3.5" />
            Warnings
          </div>
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-amber-900 dark:text-amber-200">
            {active.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {active.handoffPayload !== undefined && (
        <JsonViewer data={active.handoffPayload} label="Handoff Payload" />
      )}
    </div>
  );
}
