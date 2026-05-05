import { createFileRoute, useNavigate, useParams } from "@tanstack/react-router";
import { useEffect } from "react";
import { useAuth } from "@/context/AuthContext";
import { ClaimsHeader } from "@/components/claims/ClaimsHeader";
import { MemberResultPanel } from "@/components/claims/MemberResultPanel";
import { OpsTraceTimeline } from "@/components/claims/OpsTraceTimeline";
import { PolicyDecisionCard } from "@/components/claims/PolicyDecisionCard";
import { PipelineProgress } from "@/components/claims/PipelineProgress";
import { StatusBadge } from "@/components/claims/StatusBadge";
import { useClaims } from "@/context/ClaimsContext";
import { eventsUrl } from "@/lib/claims-api";
import type { ClaimEvent } from "@/lib/claims-types";

export const Route = createFileRoute("/claims/$claimId")({
  head: ({ params }) => ({
    meta: [
      { title: `Claim ${params.claimId} — Claims Console` },
      {
        name: "description",
        content: `Live processing trace for claim ${params.claimId}.`,
      },
      { property: "og:title", content: `Claim ${params.claimId} — Claims Console` },
    ],
  }),
  component: ClaimDetailPage,
});

function ClaimDetailPage() {
  const { claimId } = useParams({ from: "/claims/$claimId" });
  const { active, initClaim, appendEvent } = useClaims();
  const { user, isStaff } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!user) navigate({ to: "/login", replace: true });
  }, [user, navigate]);

  useEffect(() => {
    if (!active || active.claim_id !== claimId) {
      initClaim({ claim_id: claimId, user_id: "", session_id: "" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [claimId]);

  useEffect(() => {
    if (!active || active.claim_id !== claimId || active.done) return;
    const url = eventsUrl(claimId);
    const es = new EventSource(url);

    const handleData = (raw: string) => {
      try {
        const parsed = JSON.parse(raw) as ClaimEvent;
        appendEvent(claimId, parsed);
        if (
          (parsed as { type?: string }).type === "pipeline_completion" ||
          (parsed as { type?: string }).type === "error"
        ) {
          es.close();
        }
      } catch {
        // ignore malformed payloads
      }
    };

    es.onmessage = (e) => handleData(e.data);
    es.onerror = () => {};

    return () => { es.close(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.claim_id, active?.done, claimId]);

  return (
    <div className="min-h-screen bg-muted/30">
      <ClaimsHeader />
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        {/* Claim ID + status */}
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Claim
            </div>
            <h1 className="font-mono text-base font-semibold text-foreground">{claimId}</h1>
          </div>
          {active && <StatusBadge status={active.status} kind="claim" />}
        </div>

        {/* Live pipeline progress — shown to members while processing */}
        {active && !active.done && !isStaff && (
          <div className="mb-5">
            <PipelineProgress active={active} />
          </div>
        )}

        {/* Policy decision — shown once available */}
        {active?.policyDecision && (
          <div className="mb-5">
            <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Claim Decision
            </div>
            <PolicyDecisionCard decision={active.policyDecision} showRuleFindings={isStaff} />
          </div>
        )}

        <div className="grid gap-5 lg:grid-cols-2">
          <section className="rounded-lg border border-border bg-card shadow-sm">
            <div className="border-b border-border px-4 py-2.5">
              <h2 className="text-sm font-semibold text-foreground">
                {active?.done ? "Result" : "Member message"}
              </h2>
              <p className="text-xs text-muted-foreground">
                {active?.done ? "Final outcome from the claims agent." : "Live updates from the claims agent."}
              </p>
            </div>
            {active ? (
              <MemberResultPanel active={active} />
            ) : (
              <div className="p-4 text-sm text-muted-foreground">Loading…</div>
            )}
          </section>

          {isStaff && (
            <section className="rounded-lg border border-border bg-card shadow-sm">
              <div className="border-b border-border px-4 py-2.5">
                <h2 className="text-sm font-semibold text-foreground">Ops trace</h2>
                <p className="text-xs text-muted-foreground">
                  Step-by-step processing results.
                </p>
              </div>
              <div className="p-4">
                {active ? (
                  <OpsTraceTimeline active={active} />
                ) : (
                  <div className="text-sm text-muted-foreground">Loading…</div>
                )}
              </div>
            </section>
          )}
        </div>
      </main>
    </div>
  );
}
