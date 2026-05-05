import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { TRACE_STEP_KEYS, type ActiveClaimState } from "@/lib/claims-types";

const STAGE_MESSAGE: Record<string, string> = {
  TEXT_EXTRACTION:
    "We've received your claim and are getting things ready. Hang tight — this usually takes just a moment.",
  DOCUMENT_CLASSIFICATION:
    "We're taking a look at what you've sent in to make sure everything is in order.",
  DOCUMENT_REQUIREMENTS:
    "We're verifying that your submission includes everything needed to move forward.",
  DOCUMENT_EXTRACTION:
    "We're carefully going through your documents to gather the details relevant to your claim.",
  CONSISTENCY_CHECK:
    "We're doing a final review to make sure all the information lines up correctly.",
  POLICY_DECISION:
    "We're evaluating your claim against your coverage. We'll have a decision for you shortly.",
};

function getCurrentStageKey(active: ActiveClaimState): string {
  for (const key of TRACE_STEP_KEYS) {
    if (active.steps[key]?.status === "IN_PROGRESS") return key;
  }
  // No step is currently IN_PROGRESS — stay on the last step that started
  // so the message doesn't jump to POLICY_DECISION between steps.
  for (let i = TRACE_STEP_KEYS.length - 1; i >= 0; i--) {
    if (TRACE_STEP_KEYS[i] in active.steps) return TRACE_STEP_KEYS[i];
  }
  return "TEXT_EXTRACTION";
}

export function PipelineProgress({ active }: { active: ActiveClaimState }) {
  if (active.done) return null;

  const currentKey = getCurrentStageKey(active);
  const message = STAGE_MESSAGE[currentKey] ?? "Your claim is being processed.";

  return <AnimatedStatusCard key={currentKey} message={message} />;
}

function AnimatedStatusCard({ message }: { message: string }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const t = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(t);
  }, []);

  return (
    <div
      className="rounded-xl border border-border bg-card px-6 py-5 shadow-sm"
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? "translateY(0)" : "translateY(6px)",
        transition: "opacity 400ms ease, transform 400ms ease",
      }}
    >
      <div className="flex items-start gap-4">
        <div className="mt-0.5 shrink-0 rounded-full bg-primary/10 p-2">
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-1">
            Processing your claim
          </p>
          <p className="text-sm leading-relaxed text-foreground">{message}</p>
        </div>
      </div>
    </div>
  );
}
