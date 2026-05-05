#!/bin/bash
PROJECT_ID="gen-lang-client-0834637095"
PROJECT_NUMBER="813699563184"

echo "==> Workload Identity Pools:"
gcloud iam workload-identity-pools list --location=global --project="$PROJECT_ID" --format="table(name,state)"

echo ""
echo "==> Providers in 'github' pool:"
gcloud iam workload-identity-pools providers list --workload-identity-pool=github --location=global --project="$PROJECT_ID" --format="table(name,state)" 2>/dev/null || echo "Pool 'github' not found or no providers"

echo ""
echo "==> Correct WIF_PROVIDER value to use in GitHub secret:"
echo "projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github"
