import { Loader2, CheckCircle2, XCircle, AlertCircle, Circle } from "lucide-react";
import { TRACE_STEP_KEYS, type ActiveClaimState, type StepStatus } from "@/lib/claims-types";

// User-friendly labels and descriptions for each stage
const STAGE_CONTENT: Record<string, { label: string; doing: string; done: string }> = {
  TEXT_EXTRACTION: {
    label: "Reading your documents",
    doing: "We're opening and reading through each file you uploaded. This may take a moment for larger documents.",
    done: "Your documents have been read successfully.",
  },
  DOCUMENT_CLASSIFICATION: {
    label: "Identifying document types",
    doing: "We're figuring out what each document is — for example, whether it's a prescription, a hospital bill, or a lab report.",
    done: "All documents have been identified.",
  },
  DOCUMENT_REQUIREMENTS: {
    label: "Checking required documents",
    doing: "We're making sure you've submitted all the documents needed to process this type of claim.",
    done: "All required documents are present.",
  },
  DOCUMENT_EXTRACTION: {
    label: "Pulling out key details",
    doing: "We're reading through your documents to collect important information like doctor names, dates, diagnoses, and amounts.",
    done: "Key details have been collected from your documents.",
  },
  CONSISTENCY_CHECK: {
    label: "Cross-checking your documents",
    doing: "We're making sure the details across your documents match — for example, that the patient name and dates are consistent.",
    done: "Your documents are consistent with each other.",
  },
  POLICY_DECISION: {
    label: "Reviewing your claim",
    doing: "We're checking your claim against your policy coverage, limits, and eligibility to arrive at a decision.",
    done: "Your claim has been reviewed.",
  },
};

type DisplayStatus = StepStatus | "PENDING";

function StepIcon({ status }: { status: DisplayStatus }) {
  switch (status) {
    case "IN_PROGRESS":
      return <Loader2 className="h-5 w-5 animate-spin text-primary" />;
    case "COMPLETED":
      return <CheckCircle2 className="h-5 w-5 text-green-500" />;
    case "BLOCKED":
      return <XCircle className="h-5 w-5 text-red-500" />;
    case "PENDING_REUPLOAD":
      return <AlertCircle className="h-5 w-5 text-amber-500" />;
    default:
      return <Circle className="h-5 w-5 text-border" />;
  }
}

interface StageItem {
  key: string;
  status: DisplayStatus;
}

export function PipelineProgress({ active }: { active: ActiveClaimState }) {
  if (active.done) return null;

  const anyStepStarted = TRACE_STEP_KEYS.some((k) => k in active.steps);

  // Derive the synthetic TEXT_EXTRACTION status:
  // - IN_PROGRESS until any real pipeline step appears
  // - COMPLETED once at least one real step has started
  const extractionStatus: DisplayStatus = anyStepStarted ? "COMPLETED" : "IN_PROGRESS";

  const stages: StageItem[] = [
    { key: "TEXT_EXTRACTION", status: extractionStatus },
    ...TRACE_STEP_KEYS.map((key) => ({
      key,
      status: (active.steps[key]?.status ?? "PENDING") as DisplayStatus,
    })),
  ];

  return (
    <div className="rounded-lg border border-border bg-card p-5 shadow-sm">
      <p className="mb-5 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
        Processing your claim
      </p>
      <ol className="space-y-5">
        {stages.map(({ key, status }) => {
          const content = STAGE_CONTENT[key];
          const isActive = status === "IN_PROGRESS";
          const isDone = status === "COMPLETED";
          const isPending = status === "PENDING";

          return (
            <li key={key} className="flex items-start gap-3">
              <div className="mt-0.5 shrink-0">
                <StepIcon status={status} />
              </div>
              <div className="min-w-0">
                <p
                  className={`text-sm font-semibold leading-snug ${
                    isPending ? "text-muted-foreground/40" : "text-foreground"
                  }`}
                >
                  {content.label}
                </p>
                {!isPending && (
                  <p className={`mt-0.5 text-xs leading-relaxed ${isActive ? "text-muted-foreground" : isDone ? "text-muted-foreground/60" : "text-muted-foreground"}`}>
                    {isActive ? content.doing : content.done}
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
