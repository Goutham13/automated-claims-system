import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { getAuthToken } from "@/lib/auth-api";
import { API_BASE_URL } from "@/lib/claims-api";
import { StatusBadge } from "@/components/claims/StatusBadge";
import { JsonViewer } from "@/components/claims/JsonViewer";
import { Button } from "@/components/ui/button";
import { LogOut, ChevronDown, ChevronUp, RefreshCw } from "lucide-react";

interface ClaimSummary {
  claim_id: string;
  created_at: string;
  input: Record<string, unknown>;
  documents: { file_id: string; file_name: string; mime_type: string }[];
  pipeline_trace: Record<string, unknown> | null;
}

export const Route = createFileRoute("/staff/claims")({
  head: () => ({
    meta: [{ title: "Staff Dashboard — Claims" }],
  }),
  component: StaffClaimsPage,
});

function StaffClaimsPage() {
  const { user, logout, isStaff } = useAuth();
  const navigate = useNavigate();
  const [claims, setClaims] = useState<ClaimSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Record<string, "input" | "documents" | "trace">>({});

  useEffect(() => {
    if (!user) { navigate({ to: "/login", replace: true }); return; }
    if (!isStaff) { navigate({ to: "/submit", replace: true }); return; }
  }, [user, isStaff, navigate]);

  const fetchClaims = async () => {
    setLoading(true);
    setError(null);
    try {
      const token = getAuthToken();
      const res = await fetch(`${API_BASE_URL}/staff/claims`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json() as { claims: ClaimSummary[] };
      setClaims(data.claims);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load claims");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { if (isStaff) fetchClaims(); }, [isStaff]);

  const handleLogout = () => { logout(); navigate({ to: "/login", replace: true }); };
  const toggleExpand = (id: string) => setExpanded((prev) => (prev === id ? null : id));
  const getTab = (id: string) => activeTab[id] ?? "input";
  const setTab = (id: string, tab: "input" | "documents" | "trace") =>
    setActiveTab((p) => ({ ...p, [id]: tab }));

  const getFinalStatus = (trace: Record<string, unknown> | null): string =>
    (trace?.final_status as string) ?? "PROCESSING";

  return (
    <div className="min-h-screen bg-muted/30">
      {/* Header */}
      <header className="border-b border-border bg-card px-4 py-3 sm:px-6">
        <div className="mx-auto flex max-w-7xl items-center justify-between">
          <div>
            <h1 className="text-base font-semibold text-foreground">Staff Dashboard</h1>
            <p className="text-xs text-muted-foreground">All claims — Plum Health Insurance</p>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground">{user?.name}</span>
            <Button variant="outline" size="sm" onClick={handleLogout} className="gap-1.5">
              <LogOut className="h-3.5 w-3.5" />
              Sign out
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-medium text-foreground">
            {loading ? "Loading…" : `${claims.length} claim${claims.length !== 1 ? "s" : ""}`}
          </h2>
          <Button variant="outline" size="sm" onClick={fetchClaims} disabled={loading} className="gap-1.5">
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>

        {error && (
          <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-200">
            {error}
          </div>
        )}

        {!loading && claims.length === 0 && !error && (
          <div className="rounded-lg border border-border bg-card p-8 text-center text-sm text-muted-foreground">
            No claims submitted yet.
          </div>
        )}

        <div className="space-y-3">
          {claims.map((claim) => {
            const isOpen = expanded === claim.claim_id;
            const tab = getTab(claim.claim_id);
            const status = getFinalStatus(claim.pipeline_trace);
            const input = claim.input as Record<string, unknown>;

            return (
              <div key={claim.claim_id} className="rounded-lg border border-border bg-card shadow-sm">
                {/* Row header */}
                <button
                  type="button"
                  onClick={() => toggleExpand(claim.claim_id)}
                  className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left"
                >
                  <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-1">
                    <span className="font-mono text-xs text-muted-foreground">
                      {claim.claim_id.slice(0, 8)}…
                    </span>
                    <span className="text-sm font-medium text-foreground">
                      {String(input.member_id ?? "—")}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {String(input.claim_category ?? "—")}
                    </span>
                    <span className="text-xs text-foreground">
                      ${Number(input.claimed_amount ?? 0).toLocaleString()}
                    </span>
                    <StatusBadge status={status as never} kind="claim" />
                  </div>
                  <div className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                    {new Date(claim.created_at).toLocaleString()}
                    {isOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                  </div>
                </button>

                {/* Expanded detail */}
                {isOpen && (
                  <div className="border-t border-border">
                    {/* Tabs */}
                    <div className="flex border-b border-border px-4">
                      {(["input", "documents", "trace"] as const).map((t) => (
                        <button
                          key={t}
                          type="button"
                          onClick={() => setTab(claim.claim_id, t)}
                          className={`px-3 py-2 text-xs font-medium capitalize transition-colors ${
                            tab === t
                              ? "border-b-2 border-primary text-foreground"
                              : "text-muted-foreground hover:text-foreground"
                          }`}
                        >
                          {t === "trace" ? "Pipeline Trace" : t === "input" ? "Claim Input" : "Documents"}
                        </button>
                      ))}
                    </div>

                    <div className="p-4">
                      {tab === "input" && (
                        <dl className="grid gap-2 sm:grid-cols-2">
                          {Object.entries(input).map(([k, v]) => (
                            <div key={k} className="flex flex-col">
                              <dt className="text-xs text-muted-foreground">
                                {k.replace(/_/g, " ")}
                              </dt>
                              <dd className="mt-0.5 font-mono text-xs text-foreground">
                                {String(v ?? "—")}
                              </dd>
                            </div>
                          ))}
                        </dl>
                      )}

                      {tab === "documents" && (
                        <ul className="divide-y divide-border">
                          {claim.documents.map((doc) => (
                            <li key={doc.file_id} className="flex items-center justify-between py-2 text-sm">
                              <span className="font-medium text-foreground">{doc.file_name}</span>
                              <div className="ml-4 flex gap-2 text-xs text-muted-foreground">
                                <span className="font-mono">{doc.file_id}</span>
                                <span>{doc.mime_type}</span>
                              </div>
                            </li>
                          ))}
                        </ul>
                      )}

                      {tab === "trace" && (
                        claim.pipeline_trace ? (
                          <div className="space-y-3">
                            {/* Final outcome strip */}
                            <div className="flex flex-wrap gap-4 rounded-md bg-muted/50 p-3 text-xs">
                              <div>
                                <span className="text-muted-foreground">Status </span>
                                <span className="font-semibold text-foreground">
                                  {String(claim.pipeline_trace.final_status ?? "—")}
                                </span>
                              </div>
                              {claim.pipeline_trace.final_ops_summary && (
                                <div className="flex-1">
                                  <span className="text-muted-foreground">Summary </span>
                                  <span className="text-foreground">
                                    {String(claim.pipeline_trace.final_ops_summary)}
                                  </span>
                                </div>
                              )}
                            </div>
                            {/* Member message */}
                            {claim.pipeline_trace.final_member_message && (
                              <div className="rounded-md border border-border p-3 text-sm text-foreground">
                                <div className="mb-1 text-xs font-medium text-muted-foreground">
                                  Member message
                                </div>
                                {String(claim.pipeline_trace.final_member_message)}
                              </div>
                            )}
                            {/* Steps */}
                            {Array.isArray(claim.pipeline_trace.steps) &&
                              (claim.pipeline_trace.steps as Record<string, unknown>[]).map((step, i) => (
                                <div key={i} className="rounded-md border border-border p-3 text-xs">
                                  <div className="flex items-center gap-2">
                                    <span className="font-mono text-muted-foreground">Step {i + 1}</span>
                                    <span className="font-semibold uppercase text-foreground">
                                      {String(step.step_name ?? "")}
                                    </span>
                                    <span className="rounded bg-muted px-1.5 py-0.5 font-medium">
                                      {String(step.status ?? "")}
                                    </span>
                                  </div>
                                  {step.summary && (
                                    <p className="mt-1 text-muted-foreground">{String(step.summary)}</p>
                                  )}
                                  {Array.isArray(step.key_findings) && step.key_findings.length > 0 && (
                                    <ul className="mt-1.5 list-disc pl-4 text-muted-foreground">
                                      {(step.key_findings as string[]).map((f, fi) => (
                                        <li key={fi}>{f}</li>
                                      ))}
                                    </ul>
                                  )}
                                </div>
                              ))}
                            {/* Full JSON */}
                            <details className="mt-2">
                              <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
                                Raw trace JSON
                              </summary>
                              <div className="mt-2">
                                <JsonViewer data={claim.pipeline_trace} />
                              </div>
                            </details>
                          </div>
                        ) : (
                          <p className="text-sm text-muted-foreground">
                            No trace available — claim may still be processing.
                          </p>
                        )
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </main>
    </div>
  );
}
