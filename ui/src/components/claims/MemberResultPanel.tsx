import type { ActiveClaimState } from "@/lib/claims-types";
import { Loader2 } from "lucide-react";

export function MemberResultPanel({ active }: { active: ActiveClaimState }) {
  const showWaiting = !active.finalMemberMessage && !active.error && !active.done;

  return (
    <div className="min-h-[12rem] whitespace-pre-wrap p-4 text-sm leading-relaxed text-foreground">
      {showWaiting && (
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>Processing your claim…</span>
        </div>
      )}
      {active.finalMemberMessage && (
        <div>{active.finalMemberMessage}</div>
      )}
      {active.error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-200">
          <div className="text-sm font-semibold">Processing failed</div>
          <div className="mt-1 text-xs">{active.error.message}</div>
          {active.error.code !== undefined && (
            <div className="mt-1 font-mono text-[11px] opacity-70">code: {active.error.code}</div>
          )}
        </div>
      )}
    </div>
  );
}
