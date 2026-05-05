#!/bin/bash
set -e

PROJECT_ID="gen-lang-client-0834637095"
PROJECT_NUMBER="813699563184"
GITHUB_OWNER="Goutham13"
REPO_NAME="automated-claims-system"
SA_NAME="github-actions-sa"
SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

echo "==> Creating service account..."
gcloud iam service-accounts create "$SA_NAME" --project="$PROJECT_ID" --display-name="GitHub Actions SA" 2>/dev/null || echo "Service account already exists, skipping."

echo "==> Granting roles to service account..."
for role in roles/run.admin roles/storage.admin roles/iam.serviceAccountUser roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA_EMAIL" --role="$role" --quiet
done

echo "==> Creating Workload Identity Pool..."
gcloud iam workload-identity-pools create "github" --location=global --project="$PROJECT_ID" --display-name="GitHub Pool" 2>/dev/null || echo "Pool already exists, skipping."

echo "==> Creating OIDC provider..."
gcloud iam workload-identity-pools providers create-oidc "github" \
  --location=global \
  --workload-identity-pool=github \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --project="$PROJECT_ID" 2>/dev/null || echo "Provider already exists, skipping."

echo "==> Binding service account to GitHub repo..."
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$GITHUB_OWNER/$REPO_NAME" \
  --project="$PROJECT_ID"

echo ""
echo "===== ADD THESE AS GITHUB SECRETS ====="
echo "WIF_PROVIDER: projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github"
echo "WIF_SERVICE_ACCOUNT: $SA_EMAIL"
echo "======================================="
