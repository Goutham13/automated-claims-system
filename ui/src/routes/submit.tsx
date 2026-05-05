import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { ClaimsHeader } from "@/components/claims/ClaimsHeader";
import { WizardStepper } from "@/components/claims/WizardStepper";
import { Step1Claimant } from "@/components/claims/Step1Claimant";
import { Step2Details } from "@/components/claims/Step2Details";
import { Step3Documents } from "@/components/claims/Step3Documents";
import { Step4Review } from "@/components/claims/Step4Review";

export const Route = createFileRoute("/submit")({
  head: () => ({
    meta: [
      { title: "New Claim — Claims Console" },
      {
        name: "description",
        content: "Submit a new health insurance claim with supporting documents.",
      },
      { property: "og:title", content: "New Claim — Claims Console" },
      {
        property: "og:description",
        content: "Submit a new health insurance claim with supporting documents.",
      },
    ],
  }),
  component: SubmitPage,
});

const STEPS = [
  { id: 1, label: "Claimant" },
  { id: 2, label: "Details" },
  { id: 3, label: "Documents" },
  { id: 4, label: "Review" },
];

function SubmitPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [current, setCurrent] = useState(1);

  useEffect(() => {
    if (!user) navigate({ to: "/login", replace: true });
  }, [user, navigate]);

  return (
    <div className="min-h-screen bg-muted/30">
      <ClaimsHeader />
      <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-6">
          <h1 className="text-xl font-semibold tracking-tight text-foreground">
            New Claim Submission
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Provide claimant info, claim details, and supporting documents. Processing begins as soon
            as you submit.
          </p>
        </div>

        <div className="rounded-lg border border-border bg-card p-5 shadow-sm">
          <div className="mb-6">
            <WizardStepper
              steps={STEPS}
              current={current}
              onJump={(id) => setCurrent(id)}
            />
          </div>

          {current === 1 && <Step1Claimant onNext={() => setCurrent(2)} />}
          {current === 2 && (
            <Step2Details onNext={() => setCurrent(3)} onBack={() => setCurrent(1)} />
          )}
          {current === 3 && (
            <Step3Documents onNext={() => setCurrent(4)} onBack={() => setCurrent(2)} />
          )}
          {current === 4 && <Step4Review onBack={() => setCurrent(3)} />}
        </div>
      </main>
    </div>
  );
}
