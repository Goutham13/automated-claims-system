import { useClaims } from "@/context/ClaimsContext";
import { useAuth } from "@/context/AuthContext";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useEffect, useState } from "react";

interface Errors {
  member_id?: string;
  policy_id?: string;
  patient_member_id?: string;
}

export function Step1Claimant({ onNext }: { onNext: () => void }) {
  const { draft, updateDraft } = useClaims();
  const { user } = useAuth();
  const [errors, setErrors] = useState<Errors>({});

  useEffect(() => {
    if (user?.sub && !draft.member_id) {
      updateDraft({ member_id: user.sub });
    }
  }, [user?.sub]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const errs: Errors = {};
    if (!draft.member_id.trim()) errs.member_id = "Required";
    if (!draft.policy_id.trim()) errs.policy_id = "Required";
    if (draft.relationship_claim_type === "DEPENDENT" && !draft.patient_member_id.trim()) {
      errs.patient_member_id = "Required for dependent claims";
    }
    setErrors(errs);
    if (Object.keys(errs).length === 0) onNext();
  };

  return (
    <form onSubmit={submit} className="space-y-5">
      <div>
        <Label className="mb-2 block text-sm font-medium">Relationship</Label>
        <RadioGroup
          value={draft.relationship_claim_type}
          onValueChange={(v) =>
            updateDraft({ relationship_claim_type: v as "SELF" | "DEPENDENT" })
          }
          className="grid grid-cols-2 gap-2"
        >
          <Label
            htmlFor="rel-self"
            className="flex cursor-pointer items-center gap-2 rounded-md border border-border bg-background px-3 py-2 has-[:checked]:border-primary has-[:checked]:bg-primary/5"
          >
            <RadioGroupItem id="rel-self" value="SELF" />
            <span className="text-sm">Self</span>
          </Label>
          <Label
            htmlFor="rel-dep"
            className="flex cursor-pointer items-center gap-2 rounded-md border border-border bg-background px-3 py-2 has-[:checked]:border-primary has-[:checked]:bg-primary/5"
          >
            <RadioGroupItem id="rel-dep" value="DEPENDENT" />
            <span className="text-sm">Dependent</span>
          </Label>
        </RadioGroup>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {draft.relationship_claim_type === "DEPENDENT" && (
          <Field
            label="Patient Member ID"
            htmlFor="patient_member_id"
            error={errors.patient_member_id}
          >
            <Input
              id="patient_member_id"
              value={draft.patient_member_id}
              onChange={(e) => updateDraft({ patient_member_id: e.target.value })}
              placeholder="DEP-67890"
            />
          </Field>
        )}
        <Field label="Member ID" htmlFor="member_id" error={errors.member_id}>
          <Input
            id="member_id"
            value={draft.member_id}
            readOnly
            className="bg-muted/50 cursor-default"
          />
        </Field>
        <Field label="Policy ID" htmlFor="policy_id" error={errors.policy_id}>
          <Select
            value={draft.policy_id}
            onValueChange={(value) => updateDraft({ policy_id: value })}
          >
            <SelectTrigger id="policy_id" className="w-full">
              <SelectValue placeholder="Select policy" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="PLUM_GHI_2024">PLUM_GHI_2024</SelectItem>
            </SelectContent>
          </Select>
        </Field>
      </div>

      <div className="flex justify-end">
        <Button type="submit">Continue</Button>
      </div>
    </form>
  );
}

function Field({
  label,
  htmlFor,
  error,
  children,
}: {
  label: string;
  htmlFor: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <Label htmlFor={htmlFor} className="mb-1.5 block text-sm font-medium">
        {label}
      </Label>
      {children}
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  );
}
