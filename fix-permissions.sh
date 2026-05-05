#!/bin/bash
set -e

PROJECT_ID="gen-lang-client-0834637095"
REGION="us-central1"
SA_EMAIL="github-actions-sa@$PROJECT_ID.iam.gserviceaccount.com"

echo "==> Creating Artifact Registry Docker repository..."
gcloud artifacts repositories create plum-claims \
  --repository-format=docker \
  --location="$REGION" \
  --project="$PROJECT_ID" \
  --description="Plum claims system Docker images" 2>/dev/null || echo "Repository already exists, skipping."

echo "==> Granting Artifact Registry write permission to SA..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA_EMAIL" --role=roles/artifactregistry.writer --quiet
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA_EMAIL" --role=roles/artifactregistry.repoAdmin --quiet

echo ""
echo "New image registry: $REGION-docker.pkg.dev/$PROJECT_ID/plum-claims"
echo "Done."
