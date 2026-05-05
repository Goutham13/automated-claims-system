#!/bin/bash
set -e

PROJECT_ID="gen-lang-client-0834637095"
PROJECT_NUMBER="813699563184"

echo "==> Creating OIDC provider..."
gcloud iam workload-identity-pools providers create-oidc "github" \
  --location=global \
  --workload-identity-pool=github \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='Goutham13/automated-claims-system'" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --project="$PROJECT_ID"

echo ""
echo "===== UPDATE YOUR GITHUB SECRET ====="
echo "WIF_PROVIDER: projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github"
echo "====================================="
