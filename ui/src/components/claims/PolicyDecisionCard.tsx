import { CheckCircle2, AlertTriangle, XCircle, Eye } from "lucide-react";
import { cn } from "@/lib/utils";
import type { PolicyDecision, PolicyDecisionOutcome } from "@/lib/claims-types";

const DECISION_CONFIG: Record<
  PolicyDecisionOutcome,
  { label: string; icon: React.ElementType; bg: string; border: string; text: string; badge: string }
> = {
  APPROVED: {
    label: "Approved",
    icon: CheckCircle2,
    bg: "bg-emerald-50 dark:bg-emerald-950/30",
    border: "border-emerald-200 dark:border-emerald-800",
    text: "text-emerald-800 dark:text-emerald-200",
    badge: "bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-900/40 dark:text-emerald-200 dark:border-emerald-800",
  },
  PARTIAL: {
    label: "Partially Approved",
    icon: AlertTriangle,
    bg: "bg-amber-50 dark:bg-amber-950/30",
    border: "border-amber-200 dark:border-amber-800",
    text: "text-amber-900 dark:text-amber-200",
    badge: "bg-amber-100 text-amber-900 border-amber-200 dark:bg-amber-900/40 dark:text-amber-200 dark:border-amber-800",
  },
  REJECTED: {
    label: "Rejected",
    icon: XCircle,
    bg: "bg-red-50 dark:bg-red-950/30",
    border: "border-red-200 dark:border-red-800",
    text: "text-red-800 dark:text-red-200",
    badge: "bg-red-100 text-red-800 border-red-200 dark:bg-red-900/40 dark:text-red-200 dark:border-red-800",
  },
  MANUAL_REVIEW: {
    label: "Manual Review",
    icon: Eye,
    bg: "bg-orange-50 dark:bg-orange-950/30",
    border: "border-orange-200 dark:border-orange-800",
    text: "text-orange-800 dark:text-orange-200",
    badge: "bg-orange-100 text-orange-800 border-orange-200 dark:bg-orange-900/40 dark:text-orange-200 dark:border-orange-800",
  },
};

const RULE_RESULT_STYLE: Record<string, string> = {
  PASS: "text-emerald-700 dark:text-emerald-400",
  FAIL: "text-red-700 dark:text-red-400",
  INCONCLUSIVE: "text-amber-700 dark:text-amber-400",
};

function fmt(amount: number) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(amount);
}

export function PolicyDecisionCard({ decision }: { decision: PolicyDecision }) {
  const cfg = DECISION_CONFIG[decision.decision];
  const Icon = cfg.icon;
  const confidencePct = Math.round(decision.confidence_score * 100);

  return (
    <div className={cn("rounded-lg border p-4 shadow-sm", cfg.bg, cfg.border)}>
      {/* Header row */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <Icon className={cn("h-5 w-5 shrink-0", cfg.text)} />
          <span className={cn("inline-flex items-center rounded-md border px-2.5 py-1 text-sm font-semibold", cfg.badge)}>
            {cfg.label}
          </span>
        </div>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span>Confidence</span>
          <span className={cn("font-semibold", cfg.text)}>{confidencePct}%</span>
        </div>
      </div>

      {/* Amounts */}
      {decision.decision !== "REJECTED" && (
        <div className="mt-3 flex flex-wrap gap-4">
          <div>
            <div className="text-xs text-muted-foreground">Approved amount</div>
            <div className={cn("text-lg font-bold", cfg.text)}>{fmt(decision.approved_amount)}</div>
          </div>
          {decision.copay_amount > 0 && (
            <div>
              <div className="text-xs text-muted-foreground">Member co-pay</div>
              <div className="text-lg font-bold text-foreground">{fmt(decision.copay_amount)}</div>
            </div>
          )}
        </div>
      )}

      {/* Reason */}
      <p className={cn("mt-3 text-sm", cfg.text)}>{decision.reason}</p>

      {/* Rule findings */}
      {decision.rule_findings.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground select-none">
            Rule findings ({decision.rule_findings.length})
          </summary>
          <ul className="mt-2 space-y-1.5">
            {decision.rule_findings.map((f, i) => (
              <li key={i} className="flex items-start gap-2 text-xs">
                <span className={cn("shrink-0 font-semibold uppercase", RULE_RESULT_STYLE[f.result] ?? "text-foreground")}>
                  {f.result}
                </span>
                <span className="text-muted-foreground">
                  <span className="font-medium text-foreground">{f.check.replace(/_/g, " ")}</span>
                  {" — "}
                  {f.detail}
                  {f.approved_amount != null && ` (₹${f.approved_amount.toLocaleString("en-IN")})`}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
