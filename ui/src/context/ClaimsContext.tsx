import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useReducer,
  useRef,
  type ReactNode,
} from "react";
import {
  emptyDraft,
  STEP_LABELS,
  type ActiveClaimState,
  type ClaimEvent,
  type ClaimStatus,
  type CreateClaimResponse,
  type DraftForm,
  type PolicyDecision,
  type StepStatus,
  type TraceStep,
} from "@/lib/claims-types";

interface State {
  draft: DraftForm;
  active: ActiveClaimState | null;
}

type Action =
  | { type: "UPDATE_DRAFT"; patch: Partial<DraftForm> }
  | { type: "RESET_DRAFT" }
  | { type: "INIT_CLAIM"; payload: CreateClaimResponse }
  | { type: "APPEND_EVENT"; claimId: string; event: ClaimEvent }
  | { type: "CLEAR_ACTIVE" };

const initialState: State = {
  draft: emptyDraft(),
  active: null,
};

const STEP_STATUS_VALUES: StepStatus[] = [
  "COMPLETED",
  "BLOCKED",
  "PENDING_REUPLOAD",
  "SKIPPED",
  "IN_PROGRESS",
];

const AGENT_TO_STEP_KEY: Record<string, string> = {
  document_gate_agent: "DOCUMENT_CLASSIFICATION",
  document_requirements_agent: "DOCUMENT_REQUIREMENTS",
  document_extraction_agent: "DOCUMENT_EXTRACTION",
  consistency_check_agent: "CONSISTENCY_CHECK",
  policy_decision_agent: "POLICY_DECISION",
};

function coerceStatus(v: unknown): StepStatus | undefined {
  if (typeof v !== "string") return undefined;
  const upper = v.toUpperCase();
  return (STEP_STATUS_VALUES as string[]).includes(upper)
    ? (upper as StepStatus)
    : undefined;
}

function asStringArray(v: unknown): string[] | undefined {
  if (!Array.isArray(v)) return undefined;
  return v
    .map((x) => (typeof x === "string" ? x : typeof x === "object" && x ? JSON.stringify(x) : null))
    .filter((x): x is string => x !== null);
}

function deriveOverallStatus(
  steps: Record<string, TraceStep>,
  done: boolean,
  hasError: boolean,
): ClaimStatus {
  if (hasError) return "ERROR";
  const list = Object.values(steps);
  if (list.some((s) => s.status === "BLOCKED")) return "BLOCKED";
  if (list.some((s) => s.status === "PENDING_REUPLOAD")) return "WAITING_FOR_REUPLOAD";
  if (done) return "COMPLETED";
  return "PROCESSING";
}

function applyEventToActive(active: ActiveClaimState, event: ClaimEvent): ActiveClaimState {
  const next: ActiveClaimState = {
    ...active,
    steps: { ...active.steps },
    stepOrder: [...active.stepOrder],
    blockers: [...active.blockers],
    warnings: [...active.warnings],
    rawEvents: [...active.rawEvents, event],
  };

  // Error event
  if ((event as { type?: string }).type === "error") {
    const err = event as { message?: string; code?: number };
    next.error = { message: err.message ?? "Unknown error", code: err.code };
    next.done = true;
    next.status = "ERROR";
    return next;
  }

  // Completion event
  if ((event as { type?: string }).type === "pipeline_completion") {
    next.done = true;
    next.status = deriveOverallStatus(next.steps, true, false);
    return next;
  }

  // ADK event
  const adk = event as {
    content?: {
      parts?: {
        text?: string;
        function_call?: { name?: string; args?: Record<string, unknown> };
        function_response?: { name?: string; response?: Record<string, unknown> };
      }[];
    };
    partial?: boolean | null;
    is_final_response?: boolean;
    actions?: { state_delta?: Record<string, unknown> };
  };

  const parts = adk.content?.parts ?? [];
  const text = parts.map((part) => part.text ?? "").join("");
  if (typeof text === "string" && text.length > 0) {
    if (adk.is_final_response) {
      next.finalMessage = text;
      next.streamingMessage = "";
    } else if (adk.partial) {
      next.streamingMessage = next.streamingMessage + text;
    } else {
      // Non-partial, non-final intermediate message
      next.streamingMessage = text;
    }
  }

  // Only process tool parts on committed (non-partial) events.
  // partial=true events are streaming chunks; the same tool call arrives again
  // as partial=false (the authoritative version) once generation completes.
  const committedParts = adk.partial === true ? [] : parts;

  // IN_PROGRESS: mark steps for every function_call in this event.
  for (const part of committedParts) {
    const functionCall = part.function_call;
    if (functionCall?.name) {
      const stepKey = AGENT_TO_STEP_KEY[functionCall.name];
      if (stepKey) {
        const existing = next.steps[stepKey];
        next.steps[stepKey] = {
          key: stepKey,
          status:
            existing?.status && ["COMPLETED", "BLOCKED", "PENDING_REUPLOAD"].includes(existing.status)
              ? existing.status
              : "IN_PROGRESS",
          summary: existing?.summary ?? `${STEP_LABELS[stepKey] ?? stepKey} in progress`,
          key_findings: existing?.key_findings,
          raw: existing?.raw,
          updated_at: new Date().toISOString(),
        };
        if (!next.stepOrder.includes(stepKey)) next.stepOrder.push(stepKey);
      }
    }
  }

  // COMPLETION: group all function_responses by stepKey so multiple per-file
  // responses for the same agent (e.g. two document_gate_agent calls) are
  // merged rather than the last one overwriting the earlier ones.
  const responseGroups: Record<string, Array<Record<string, unknown>>> = {};
  for (const part of committedParts) {
    const functionResponse = part.function_response;
    if (!functionResponse?.name) continue;
    const stepKey = AGENT_TO_STEP_KEY[functionResponse.name];
    if (!stepKey) continue;
    const rawResponse = functionResponse.response;
    if (!rawResponse || typeof rawResponse !== "object") continue;
    if (!responseGroups[stepKey]) responseGroups[stepKey] = [];
    responseGroups[stepKey].push(rawResponse as Record<string, unknown>);
  }

  for (const [stepKey, payloads] of Object.entries(responseGroups)) {
    const multi = payloads.length > 1;

    // Status: most severe across all responses.
    let status: StepStatus = "COMPLETED";
    for (const p of payloads) {
      const outcome = String(p.outcome ?? "").toUpperCase();
      if (outcome === "BLOCKED") { status = "BLOCKED"; break; }
      if (outcome === "PENDING_REUPLOAD") status = "PENDING_REUPLOAD";
    }

    // Summary: join all ops_messages, prefixed with file_id when multiple.
    const opsMsgs = payloads
      .map((p) => {
        const msg = typeof p.ops_message === "string" ? p.ops_message : "";
        const fileId = typeof p.file_id === "string" ? p.file_id : "";
        return multi && fileId ? `[${fileId}] ${msg}` : msg;
      })
      .filter(Boolean);
    const summary = opsMsgs.join(" · ") || `${STEP_LABELS[stepKey] ?? stepKey} completed`;

    // key_findings: flatten all per-response findings, prefixed with file_id when multiple.
    const allFindings: string[] = [];
    for (const p of payloads) {
      const fileId = typeof p.file_id === "string" ? p.file_id : "";
      for (const f of asStringArray(p.key_findings) ?? []) {
        allFindings.push(multi && fileId ? `[${fileId}] ${f}` : f);
      }
    }

    next.steps[stepKey] = {
      key: stepKey,
      status,
      summary,
      key_findings: allFindings.length > 0 ? allFindings : undefined,
      raw: multi ? payloads : payloads[0],
      updated_at: new Date().toISOString(),
    };
    if (!next.stepOrder.includes(stepKey)) next.stepOrder.push(stepKey);
  }

  const delta = adk.actions?.state_delta;
  if (delta && typeof delta === "object") {
    // final_member_message
    const fmm = (delta as Record<string, unknown>).final_member_message;
    if (typeof fmm === "string") next.finalMemberMessage = fmm;

    // blockers / warnings
    const blockers = asStringArray((delta as Record<string, unknown>).blockers);
    if (blockers) next.blockers = blockers;
    const warnings = asStringArray((delta as Record<string, unknown>).warnings);
    if (warnings) next.warnings = warnings;

    // handoff_payload
    if ("handoff_payload" in delta) {
      next.handoffPayload = (delta as Record<string, unknown>).handoff_payload;
    }

    // policy_decision
    const pd = (delta as Record<string, unknown>).policy_decision;
    if (pd && typeof pd === "object") {
      next.policyDecision = pd as PolicyDecision;
    }

    // final_status
    const fs = (delta as Record<string, unknown>).final_status;
    if (typeof fs === "string") {
      next.finalStatus = fs;
    }

    // step results: retain only root-level step updates from pipeline_trace flattening.
    for (const [key, value] of Object.entries(delta)) {
      if (!value || typeof value !== "object") continue;
      const v = value as Record<string, unknown>;
      const status = coerceStatus(v.status);
      if (!status) continue;

      // Heuristic: treat any state_delta key with a `status` field as a trace step.
      const stepKey = key.toUpperCase();
      const existing = next.steps[stepKey];
      const stepObj: TraceStep = {
        key: stepKey,
        status,
        summary:
          typeof v.summary === "string"
            ? v.summary
            : typeof v.message === "string"
              ? (v.message as string)
              : existing?.summary,
        key_findings: asStringArray(v.key_findings) ?? existing?.key_findings,
        raw: v,
        updated_at: new Date().toISOString(),
      };
      next.steps[stepKey] = stepObj;
      if (!next.stepOrder.includes(stepKey)) next.stepOrder.push(stepKey);
    }
  }

  next.status = deriveOverallStatus(next.steps, next.done, !!next.error);
  return next;
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "UPDATE_DRAFT":
      return { ...state, draft: { ...state.draft, ...action.patch } };
    case "RESET_DRAFT":
      return { ...state, draft: emptyDraft() };
    case "INIT_CLAIM":
      return {
        ...state,
        active: {
          claim_id: action.payload.claim_id,
          user_id: action.payload.user_id,
          session_id: action.payload.session_id,
          status: "PROCESSING",
          streamingMessage: "",
          finalMessage: "",
          steps: {},
          stepOrder: [],
          blockers: [],
          warnings: [],
          policyDecision: undefined,
          finalStatus: undefined,
          rawEvents: [],
          done: false,
        },
      };
    case "APPEND_EVENT": {
      if (!state.active || state.active.claim_id !== action.claimId) return state;
      return { ...state, active: applyEventToActive(state.active, action.event) };
    }
    case "CLEAR_ACTIVE":
      return { ...state, active: null };
    default:
      return state;
  }
}

interface ClaimsContextValue {
  draft: DraftForm;
  active: ActiveClaimState | null;
  updateDraft: (patch: Partial<DraftForm>) => void;
  resetDraft: () => void;
  initClaim: (payload: CreateClaimResponse) => void;
  appendEvent: (claimId: string, event: ClaimEvent) => void;
  clearActive: () => void;
}

const ClaimsContext = createContext<ClaimsContextValue | null>(null);

export function ClaimsProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  // Keep refs to allow stable callbacks
  const dispatchRef = useRef(dispatch);
  dispatchRef.current = dispatch;

  const updateDraft = useCallback(
    (patch: Partial<DraftForm>) => dispatchRef.current({ type: "UPDATE_DRAFT", patch }),
    [],
  );
  const resetDraft = useCallback(() => dispatchRef.current({ type: "RESET_DRAFT" }), []);
  const initClaim = useCallback(
    (payload: CreateClaimResponse) => dispatchRef.current({ type: "INIT_CLAIM", payload }),
    [],
  );
  const appendEvent = useCallback(
    (claimId: string, event: ClaimEvent) =>
      dispatchRef.current({ type: "APPEND_EVENT", claimId, event }),
    [],
  );
  const clearActive = useCallback(() => dispatchRef.current({ type: "CLEAR_ACTIVE" }), []);

  const value = useMemo<ClaimsContextValue>(
    () => ({
      draft: state.draft,
      active: state.active,
      updateDraft,
      resetDraft,
      initClaim,
      appendEvent,
      clearActive,
    }),
    [state.draft, state.active, updateDraft, resetDraft, initClaim, appendEvent, clearActive],
  );

  return <ClaimsContext.Provider value={value}>{children}</ClaimsContext.Provider>;
}

export function useClaims() {
  const ctx = useContext(ClaimsContext);
  if (!ctx) throw new Error("useClaims must be used within ClaimsProvider");
  return ctx;
}
