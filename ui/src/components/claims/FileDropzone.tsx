import { useCallback, useRef, useState } from "react";
import { Upload, X, FileText, Image as ImageIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

const ACCEPTED = ["application/pdf", "image/jpeg", "image/png", "image/jpg"];
const ACCEPT_ATTR = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";
const MAX_FILE_SIZE = 10 * 1024 * 1024;

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

function isAccepted(file: File): boolean {
  if (ACCEPTED.includes(file.type)) return true;
  const lower = file.name.toLowerCase();
  return [".pdf", ".jpg", ".jpeg", ".png"].some((ext) => lower.endsWith(ext));
}

export function FileDropzone({
  files,
  onChange,
}: {
  files: File[];
  onChange: (files: File[]) => void;
}) {
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback(
    (incoming: FileList | File[]) => {
      const arr = Array.from(incoming);
      const accepted: File[] = [];
      const rejected: string[] = [];
      for (const f of arr) {
        if (f.size > MAX_FILE_SIZE) {
          rejected.push(`${f.name} (exceeds 10 MB limit)`);
        } else if (isAccepted(f)) {
          accepted.push(f);
        } else {
          rejected.push(`${f.name} (unsupported type)`);
        }
      }
      // Dedupe by name+size
      const existingKeys = new Set(files.map((f) => `${f.name}:${f.size}`));
      const fresh = accepted.filter((f) => !existingKeys.has(`${f.name}:${f.size}`));
      if (rejected.length) {
        setError(`Cannot upload: ${rejected.join(", ")}`);
      } else {
        setError(null);
      }
      onChange([...files, ...fresh]);
    },
    [files, onChange],
  );

  const remove = (idx: number) => {
    const next = files.slice();
    next.splice(idx, 1);
    onChange(next);
  };

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
        }}
        className={cn(
          "flex flex-col items-center justify-center rounded-md border-2 border-dashed border-border bg-muted/30 px-6 py-10 text-center transition-colors",
          drag && "border-primary bg-primary/5",
        )}
      >
        <Upload className="mb-2 h-6 w-6 text-muted-foreground" />
        <p className="text-sm font-medium text-foreground">
          Drag &amp; drop files here, or click to browse
        </p>
        <p className="mt-1 text-xs text-muted-foreground">PDF, JPG, or PNG · Max 10 MB per file · Multiple files allowed</p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-3"
          onClick={() => inputRef.current?.click()}
        >
          Choose files
        </Button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT_ATTR}
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.length) addFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
      {files.length > 0 && (
        <ul className="divide-y divide-border rounded-md border border-border bg-background">
          {files.map((f, i) => {
            const isImg = f.type.startsWith("image/");
            return (
              <li key={`${f.name}-${i}`} className="flex items-center gap-3 px-3 py-2">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                  {isImg ? <ImageIcon className="h-4 w-4" /> : <FileText className="h-4 w-4" />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-foreground">{f.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {formatBytes(f.size)} · {f.type || "unknown"}
                  </div>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => remove(i)}
                  className="h-8 w-8 p-0"
                  aria-label={`Remove ${f.name}`}
                >
                  <X className="h-4 w-4" />
                </Button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
