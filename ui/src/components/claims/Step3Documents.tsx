import { useState } from "react";
import { useClaims } from "@/context/ClaimsContext";
import { Button } from "@/components/ui/button";
import { FileDropzone } from "./FileDropzone";
import { CLAIM_CATEGORY_LABELS, type ClaimCategory } from "@/lib/claims-types";
import { CheckCircle2, Circle } from "lucide-react";

const DOC_LABELS: Record<string, string> = {
  PRESCRIPTION: "Doctor's Prescription",
  HOSPITAL_BILL: "Hospital Bill / Invoice",
  LAB_REPORT: "Lab Report",
  DIAGNOSTIC_REPORT: "Diagnostic Report (X-ray, MRI, CT Scan, etc.)",
  PHARMACY_BILL: "Pharmacy Bill",
  DENTAL_REPORT: "Dental Report",
  DISCHARGE_SUMMARY: "Discharge Summary",
};

const DOC_REQUIREMENTS: Record<ClaimCategory, { required: string[]; optional: string[] }> = {
  CONSULTATION: {
    required: ["PRESCRIPTION", "HOSPITAL_BILL"],
    optional: ["LAB_REPORT", "DIAGNOSTIC_REPORT"],
  },
  DIAGNOSTIC: {
    required: ["PRESCRIPTION", "LAB_REPORT", "HOSPITAL_BILL"],
    optional: ["DISCHARGE_SUMMARY"],
  },
  PHARMACY: {
    required: ["PRESCRIPTION", "PHARMACY_BILL"],
    optional: [],
  },
  DENTAL: {
    required: ["HOSPITAL_BILL"],
    optional: ["PRESCRIPTION", "DENTAL_REPORT"],
  },
  VISION: {
    required: ["PRESCRIPTION", "HOSPITAL_BILL"],
    optional: [],
  },
  ALTERNATIVE_MEDICINE: {
    required: ["PRESCRIPTION", "HOSPITAL_BILL"],
    optional: [],
  },
};

export function Step3Documents({
  onNext,
  onBack,
}: {
  onNext: () => void;
  onBack: () => void;
}) {
  const { draft, updateDraft } = useClaims();
  const [error, setError] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (draft.documents.length === 0) {
      setError("Attach at least one document.");
      return;
    }
    setError(null);
    onNext();
  };

  const reqs = draft.claim_category ? DOC_REQUIREMENTS[draft.claim_category as ClaimCategory] : null;

  return (
    <form onSubmit={submit} className="space-y-5">
      {reqs && (
        <div className="rounded-md border border-border bg-muted/30 p-4 text-sm">
          <p className="mb-3 font-medium text-foreground">
            Required documents for{" "}
            <span className="text-primary">
              {CLAIM_CATEGORY_LABELS[draft.claim_category as ClaimCategory]}
            </span>
          </p>

          <div className="space-y-1.5">
            {reqs.required.map((doc) => (
              <div key={doc} className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 shrink-0 text-red-500" />
                <span className="text-foreground">{DOC_LABELS[doc]}</span>
                <span className="ml-auto shrink-0 rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-red-700 dark:bg-red-950/50 dark:text-red-400">
                  Required
                </span>
              </div>
            ))}
            {reqs.optional.map((doc) => (
              <div key={doc} className="flex items-center gap-2 opacity-70">
                <Circle className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="text-muted-foreground">{DOC_LABELS[doc]}</span>
                <span className="ml-auto shrink-0 rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                  Optional
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <FileDropzone
        files={draft.documents}
        onChange={(files) => updateDraft({ documents: files })}
      />
      {error && <p className="text-xs text-red-600">{error}</p>}
      <div className="flex justify-between">
        <Button type="button" variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button type="submit">Continue</Button>
      </div>
    </form>
  );
}
