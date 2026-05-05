#!/bin/bash
set -e

PROJECT_ID="gen-lang-client-0834637095"
SA="813699563184-compute@developer.gserviceaccount.com"

gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA" --role=roles/cloudsql.client

gcloud secrets add-iam-policy-binding DATABASE_URL --project="$PROJECT_ID" --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor

echo "Done — IAM bindings applied."
