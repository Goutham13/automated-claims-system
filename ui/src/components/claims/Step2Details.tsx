import { useState } from "react";
import { useClaims } from "@/context/ClaimsContext";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  CLAIM_CATEGORIES,
  CLAIM_CATEGORY_LABELS,
  type ClaimCategory,
} from "@/lib/claims-types";

interface Errors {
  claim_category?: string;
  treatment_date?: string;
  claimed_amount?: string;
}

export function Step2Details({
  onNext,
  onBack,
}: {
  onNext: () => void;
  onBack: () => void;
}) {
  const { draft, updateDraft } = useClaims();
  const [errors, setErrors] = useState<Errors>({});

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const errs: Errors = {};
    if (!draft.claim_category) errs.claim_category = "Select a category";
    if (!draft.treatment_date) errs.treatment_date = "Select a date";
    const amount = Number(draft.claimed_amount);
    if (!draft.claimed_amount || Number.isNaN(amount) || amount <= 0) {
      errs.claimed_amount = "Amount must be greater than 0";
    }
    setErrors(errs);
    if (Object.keys(errs).length === 0) onNext();
  };

  const today = new Date().toISOString().split("T")[0];

  return (
    <form onSubmit={submit} className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <Label className="mb-1.5 block text-sm font-medium">Claim Category</Label>
          <Select
            value={draft.claim_category || undefined}
            onValueChange={(v) => updateDraft({ claim_category: v as ClaimCategory })}
          >
            <SelectTrigger>
              <SelectValue placeholder="Select a category" />
            </SelectTrigger>
            <SelectContent>
              {CLAIM_CATEGORIES.map((c) => (
                <SelectItem key={c} value={c}>
                  {CLAIM_CATEGORY_LABELS[c]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {errors.claim_category && (
            <p className="mt-1 text-xs text-red-600">{errors.claim_category}</p>
          )}
        </div>

        <div>
          <Label htmlFor="treatment_date" className="mb-1.5 block text-sm font-medium">
            Treatment Date
          </Label>
          <Input
            id="treatment_date"
            type="date"
            max={today}
            min="1900-01-01"
            value={draft.treatment_date}
            onChange={(e) => updateDraft({ treatment_date: e.target.value })}
          />
          {errors.treatment_date && (
            <p className="mt-1 text-xs text-red-600">{errors.treatment_date}</p>
          )}
        </div>

        <div>
          <Label htmlFor="claimed_amount" className="mb-1.5 block text-sm font-medium">
            Claimed Amount
          </Label>
          <div className="relative">
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
              $
            </span>
            <Input
              id="claimed_amount"
              type="number"
              inputMode="decimal"
              min={0}
              step="0.01"
              className="pl-7"
              value={draft.claimed_amount}
              onChange={(e) => updateDraft({ claimed_amount: e.target.value })}
              placeholder="0.00"
            />
          </div>
          {errors.claimed_amount && (
            <p className="mt-1 text-xs text-red-600">{errors.claimed_amount}</p>
          )}
        </div>
      </div>

      <div className="flex items-start gap-3 rounded-md border border-border bg-muted/40 p-3">
        <Checkbox
          id="has_pre_authorization"
          checked={!!draft.has_pre_authorization}
          onCheckedChange={(checked) =>
            updateDraft({ has_pre_authorization: checked === true })
          }
          className="mt-0.5"
        />
        <div>
          <Label htmlFor="has_pre_authorization" className="cursor-pointer text-sm font-medium">
            Pre-authorization obtained
          </Label>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Check this if you received pre-approval from the insurer before treatment (required for
            high-value diagnostics like MRI, CT Scan, or PET Scan above the threshold).
          </p>
        </div>
      </div>

      <div className="flex justify-between">
        <Button type="button" variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button type="submit">Continue</Button>
      </div>
    </form>
  );
}
