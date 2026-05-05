import { useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { useClaims } from "@/context/ClaimsContext";
import { Button } from "@/components/ui/button";
import { CLAIM_CATEGORY_LABELS } from "@/lib/claims-types";
import { createClaim } from "@/lib/claims-api";

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

export function Step4Review({ onBack }: { onBack: () => void }) {
  const { draft, initClaim } = useClaims();
  const navigate = useNavigate();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await createClaim(draft);
      initClaim(res);
      navigate({ to: "/claims/$claimId", params: { claimId: res.claim_id } });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submission failed");
      setSubmitting(false);
    }
  };

  const amount = Number(draft.claimed_amount);
  const fmtAmount = Number.isFinite(amount)
    ? amount.toLocaleString(undefined, { style: "currency", currency: "USD" })
    : draft.claimed_amount;

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <Section title="Claimant">
          <Row k="Relationship" v={draft.relationship_claim_type === "SELF" ? "Self" : "Dependent"} />
          {draft.relationship_claim_type === "DEPENDENT" && (
            <Row k="Patient Member ID" v={draft.patient_member_id} mono />
          )}
          <Row k="Member ID" v={draft.member_id} mono />
          <Row k="Policy ID" v={draft.policy_id} mono />
        </Section>
        <Section title="Claim">
          <Row
            k="Category"
            v={draft.claim_category ? CLAIM_CATEGORY_LABELS[draft.claim_category] : "—"}
          />
          <Row k="Treatment Date" v={draft.treatment_date || "—"} />
          <Row k="Amount" v={fmtAmount} />
          <Row k="Pre-authorization" v={draft.has_pre_authorization ? "Yes" : "No"} />
        </Section>
      </div>

      <Section title={`Documents (${draft.documents.length})`}>
        {draft.documents.length === 0 ? (
          <p className="text-sm text-muted-foreground">None</p>
        ) : (
          <ul className="divide-y divide-border">
            {draft.documents.map((f, i) => (
              <li key={i} className="flex items-center justify-between py-2 text-sm">
                <span className="truncate">{f.name}</span>
                <span className="ml-3 shrink-0 text-xs text-muted-foreground">
                  {formatBytes(f.size)} · {f.type || "unknown"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-200">
          {error}
        </div>
      )}

      <div className="flex justify-between">
        <Button type="button" variant="outline" onClick={onBack} disabled={submitting}>
          Back
        </Button>
        <Button type="button" onClick={submit} disabled={submitting}>
          {submitting ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Submitting…
            </>
          ) : (
            "Submit Claim"
          )}
        </Button>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-card p-4">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function Row({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-sm">
      <span className="text-muted-foreground">{k}</span>
      <span className={mono ? "font-mono text-foreground" : "text-foreground"}>{v || "—"}</span>
    </div>
  );
}
