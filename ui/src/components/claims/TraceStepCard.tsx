import type { TraceStep } from "@/lib/claims-types";
import { STEP_LABELS } from "@/lib/claims-types";
import { StatusBadge } from "./StatusBadge";
import { JsonViewer } from "./JsonViewer";

export function TraceStepCard({ step, index }: { step: TraceStep; index: number }) {
  const label = STEP_LABELS[step.key] ?? step.key.replace(/_/g, " ");
  return (
    <div className="relative pl-8">
      {/* Timeline dot */}
      <span
        aria-hidden
        className="absolute left-2.5 top-3 -ml-px h-3 w-3 rounded-full border-2 border-background bg-primary ring-2 ring-primary/30"
      />
      <div className="rounded-md border border-border bg-card p-3 shadow-sm">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono uppercase tracking-wide text-muted-foreground">
                Step {index + 1}
              </span>
              <StatusBadge status={step.status} kind="step" />
            </div>
            <h3 className="mt-1 text-sm font-semibold text-foreground">{label}</h3>
          </div>
        </div>
        {step.summary && (
          <p className="mt-2 text-sm text-muted-foreground">{step.summary}</p>
        )}
        {step.key_findings && step.key_findings.length > 0 && (
          <div className="mt-2">
            <div className="mb-1 text-xs font-medium text-foreground">Key findings</div>
            <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
              {step.key_findings.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          </div>
        )}
        <div className="mt-3">
          <JsonViewer data={step.raw} />
        </div>
      </div>
    </div>
  );
}
