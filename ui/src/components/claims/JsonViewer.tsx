import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

export function JsonViewer({
  data,
  label = "Raw JSON",
  defaultOpen = false,
  className,
}: {
  data: unknown;
  label?: string;
  defaultOpen?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  let body = "";
  try {
    body = JSON.stringify(data, null, 2);
  } catch {
    body = String(data);
  }
  return (
    <div className={cn("rounded-md border border-border bg-muted/40", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-left text-xs font-medium text-muted-foreground hover:text-foreground"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5" />
        )}
        {label}
      </button>
      {open && (
        <pre className="max-h-80 overflow-auto border-t border-border bg-background/60 p-3 font-mono text-[11px] leading-relaxed text-foreground">
          {body}
        </pre>
      )}
    </div>
  );
}
