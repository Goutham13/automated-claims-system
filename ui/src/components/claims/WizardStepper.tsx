import { cn } from "@/lib/utils";
import { Check } from "lucide-react";

export interface WizardStep {
  id: number;
  label: string;
}

export function WizardStepper({
  steps,
  current,
  onJump,
}: {
  steps: WizardStep[];
  current: number;
  onJump?: (id: number) => void;
}) {
  return (
    <ol className="flex w-full items-center gap-2">
      {steps.map((step, idx) => {
        const isDone = current > step.id;
        const isActive = current === step.id;
        return (
          <li key={step.id} className="flex flex-1 items-center gap-2">
            <button
              type="button"
              onClick={() => onJump && step.id < current && onJump(step.id)}
              disabled={!onJump || step.id >= current}
              className={cn(
                "flex items-center gap-2 rounded-md px-2 py-1 text-left transition-colors",
                onJump && step.id < current && "hover:bg-muted",
                (!onJump || step.id >= current) && "cursor-default",
              )}
            >
              <span
                className={cn(
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold",
                  isDone &&
                    "border-primary bg-primary text-primary-foreground",
                  isActive && "border-primary bg-background text-primary",
                  !isDone && !isActive && "border-border bg-background text-muted-foreground",
                )}
              >
                {isDone ? <Check className="h-3.5 w-3.5" /> : step.id}
              </span>
              <span
                className={cn(
                  "hidden text-xs font-medium sm:inline",
                  isActive ? "text-foreground" : "text-muted-foreground",
                )}
              >
                {step.label}
              </span>
            </button>
            {idx < steps.length - 1 && (
              <div
                className={cn(
                  "h-px flex-1",
                  current > step.id ? "bg-primary" : "bg-border",
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
