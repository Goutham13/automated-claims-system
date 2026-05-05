import type { CreateClaimResponse, DraftForm } from "./claims-types";
import { getAuthToken } from "./auth-api";

export const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ||
  "http://localhost:8000";

export async function createClaim(draft: DraftForm): Promise<CreateClaimResponse> {
  const fd = new FormData();
  fd.append("member_id", draft.member_id);
  fd.append("policy_id", draft.policy_id);
  fd.append("claim_category", draft.claim_category);
  fd.append("treatment_date", draft.treatment_date);
  fd.append("claimed_amount", String(Number(draft.claimed_amount)));
  fd.append("relationship_claim_type", draft.relationship_claim_type);
  if (draft.relationship_claim_type === "DEPENDENT" && draft.patient_member_id) {
    fd.append("patient_member_id", draft.patient_member_id);
  }
  fd.append("has_pre_authorization", String(draft.has_pre_authorization));
  for (const file of draft.documents) {
    fd.append("documents", file, file.name);
  }

  const token = getAuthToken();
  const res = await fetch(`${API_BASE_URL}/claims`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: fd,
  });

  if (!res.ok) {
    let detail = "";
    try {
      detail = await res.text();
    } catch {
      // ignore
    }
    throw new Error(
      `Failed to create claim (HTTP ${res.status})${detail ? `: ${detail.slice(0, 200)}` : ""}`,
    );
  }

  return (await res.json()) as CreateClaimResponse;
}

export function eventsUrl(claimId: string): string {
  return `${API_BASE_URL}/claims/${encodeURIComponent(claimId)}/events`;
}
