export const CLAIM_CATEGORIES = [
  "CONSULTATION",
  "DIAGNOSTIC",
  "PHARMACY",
  "DENTAL",
  "VISION",
  "ALTERNATIVE_MEDICINE",
] as const;
export type ClaimCategory = (typeof CLAIM_CATEGORIES)[number];

export const RELATIONSHIP_TYPES = ["SELF", "DEPENDENT"] as const;
export type RelationshipType = (typeof RELATIONSHIP_TYPES)[number];

export const TRACE_STEP_KEYS = [
  "DOCUMENT_CLASSIFICATION",
  "DOCUMENT_REQUIREMENTS",
  "DOCUMENT_EXTRACTION",
  "CONSISTENCY_CHECK",
  "POLICY_DECISION",
] as const;
export type TraceStepKey = (typeof TRACE_STEP_KEYS)[number];

export type StepStatus =
  | "COMPLETED"
  | "BLOCKED"
  | "PENDING_REUPLOAD"
  | "SKIPPED"
  | "IN_PROGRESS";

export interface TraceStep {
  key: string;
  status: StepStatus;
  summary?: string;
  key_findings?: string[];
  raw?: unknown;
  updated_at?: string;
}

export type ClaimStatus =
  | "PROCESSING"
  | "WAITING_FOR_REUPLOAD"
  | "BLOCKED"
  | "COMPLETED"
  | "ERROR";

export type PolicyDecisionOutcome = "APPROVED" | "PARTIAL" | "REJECTED" | "MANUAL_REVIEW";

export interface RuleFinding {
  check: string;
  result: "PASS" | "FAIL" | "INCONCLUSIVE";
  detail: string;
  approved_amount?: number | null;
}

export interface PolicyDecision {
  decision: PolicyDecisionOutcome;
  approved_amount: number;
  copay_amount: number;
  reason: string;
  confidence_score: number;
  rule_findings: RuleFinding[];
}

export interface DraftForm {
  member_id: string;
  policy_id: string;
  claim_category: ClaimCategory | "";
  treatment_date: string; // YYYY-MM-DD
  claimed_amount: string; // keep as string in form, parsed on submit
  relationship_claim_type: RelationshipType;
  patient_member_id: string;
  has_pre_authorization: boolean;
  documents: File[];
}

export interface CreateClaimResponse {
  claim_id: string;
  user_id: string;
  session_id: string;
}

export interface ClaimErrorEvent {
  type: "error";
  message: string;
  code?: number;
  created_at?: string;
}

export interface ClaimCompletionEvent {
  type: "pipeline_completion";
  pipeline_complete: true;
  author?: string;
  content?: { parts?: { text?: string }[] };
  claim_id?: string;
  created_at?: string;
}

export interface AdkEvent {
  author?: string;
  content?: {
    parts?: {
      text?: string;
      function_call?: {
        name?: string;
        args?: Record<string, unknown>;
      };
      function_response?: {
        name?: string;
        response?: Record<string, unknown>;
      };
    }[];
  };
  partial?: boolean | null;
  is_final_response?: boolean;
  actions?: { state_delta?: Record<string, unknown> };
  invocation_id?: string;
  created_at?: string;
  user_id?: string;
  session_id?: string;
  claim_id?: string;
  type?: undefined;
}

export type ClaimEvent = AdkEvent | ClaimCompletionEvent | ClaimErrorEvent;

export interface ActiveClaimState {
  claim_id: string;
  user_id?: string;
  session_id?: string;
  status: ClaimStatus;
  streamingMessage: string;
  finalMessage: string;
  finalMemberMessage?: string;
  steps: Record<string, TraceStep>;
  stepOrder: string[];
  blockers: string[];
  warnings: string[];
  handoffPayload?: unknown;
  policyDecision?: PolicyDecision;
  finalStatus?: string;
  rawEvents: ClaimEvent[];
  error?: { message: string; code?: number };
  done: boolean;
}

export const emptyDraft = (): DraftForm => ({
  member_id: "",
  policy_id: "PLUM_GHI_2024",
  claim_category: "",
  treatment_date: "",
  claimed_amount: "",
  relationship_claim_type: "SELF",
  patient_member_id: "",
  has_pre_authorization: false,
  documents: [],
});

export const CLAIM_CATEGORY_LABELS: Record<ClaimCategory, string> = {
  CONSULTATION: "Consultation",
  DIAGNOSTIC: "Diagnostic",
  PHARMACY: "Pharmacy",
  DENTAL: "Dental",
  VISION: "Vision",
  ALTERNATIVE_MEDICINE: "Alternative Medicine",
};

export const STEP_LABELS: Record<string, string> = {
  DOCUMENT_CLASSIFICATION: "Document Classification",
  DOCUMENT_REQUIREMENTS: "Document Requirements",
  DOCUMENT_EXTRACTION: "Document Extraction",
  CONSISTENCY_CHECK: "Consistency Check",
  POLICY_DECISION: "Policy Decision",
};
