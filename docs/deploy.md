# Deploying

Three pieces, each on its own host (D-003). Set them up in this order: the embedder first (the API needs
its URL), then the API (the front end needs its URL), then the front end.

```
GitHub Pages (front end, PDFs)  ──►  Render (API: search, answer, check)  ──►  Cloud Run (embedding model)
                                                 └──►  OpenAI or Gemini (answers, when a key is set)
```

Nothing here has been deployed yet: the build session had no GCP credentials or Render API key.

## 0. Merge to `main`

Render's blueprint and the Pages workflow both deploy from `main`, so merge the pull request first.

## 1. The embedder on Google Cloud Run

You need a Google Cloud project with billing enabled, and the `gcloud` CLI (Cloud Shell has it, and the
repository can be cloned there). Set a budget alert on the billing account first (Billing > Budgets &
alerts): at this scale the cost should be small, but an alert makes sure. Check
[Cloud Run pricing](https://cloud.google.com/run/pricing) for the free tier in your region. The commands
assume `australia-southeast1` (Sydney), close to both Australian users and Render's Singapore region.

```bash
PROJECT=your-project-id
REGION=australia-southeast1
gcloud config set project $PROJECT
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
gcloud artifacts repositories create econ --repository-format=docker --location=$REGION

# A random token that Render will present; keep a copy for step 2.
TOKEN=$(openssl rand -hex 24)
printf %s "$TOKEN" | gcloud secrets create econ-embedder-token --data-file=-
gcloud secrets add-iam-policy-binding econ-embedder-token \
  --member="serviceAccount:$(gcloud projects describe $PROJECT --format='value(projectNumber)')-compute@developer.gserviceaccount.com" \
  --role=roles/secretmanager.secretAccessor

# Build (from the repository root, about 5 to 10 minutes) and deploy.
IMAGE=$REGION-docker.pkg.dev/$PROJECT/econ/embedder:$(git rev-parse --short=12 HEAD)
gcloud builds submit --config deploy/embedder/cloudbuild.yaml --substitutions _IMAGE=$IMAGE .
gcloud run deploy econ-embedder --region $REGION --image $IMAGE \
  --cpu 1 --memory 2Gi --cpu-boost --min-instances 0 --max-instances 2 --concurrency 8 --timeout 60 \
  --allow-unauthenticated --set-secrets EMBEDDER_TOKEN=econ-embedder-token:latest

URL=$(gcloud run services describe econ-embedder --region $REGION --format='value(status.url)')
curl -s -H "Authorization: Bearer $TOKEN" $URL/health     # shows the model, its revision and hash
echo "EMBEDDER_URL=$URL"; echo "EMBEDDER_TOKEN=$TOKEN"    # both go to Render in step 2
```

- `--allow-unauthenticated` lets Render reach the service without a Google identity; the bearer token
  keeps everyone else out. The stronger alternative, IAM-authenticated calls, would need a Google
  service-account key stored on Render.
- If the deploy is refused because an organisation policy forbids public (`allUsers`) access, the
  project's administrator must allow it for this service, or use a project outside that policy.
- If the build is refused for missing permissions, the error names the service account and the role it
  lacks; grant it (`gcloud projects add-iam-policy-binding`) and run the build again.
- `--max-instances 2` caps what a flood of requests could cost.
- Sizing, measured locally: the service holds about 720 MB with the model loaded; a warm query takes
  about 45 ms on one vCPU; loading the model takes about 2 s, on top of Cloud Run's own start-up.
- To redeploy from GitHub instead, set up Workload Identity Federation and the repository variables
  named at the top of `.github/workflows/embedder.yml`, then run that workflow by hand.

## 2. The API on Render

1. Render dashboard > **New > Blueprint** > connect this repository, branch `main`. Render reads
   `render.yaml`: one free Python web service, `econ-api`, in Singapore.
2. Fill in the environment variables the blueprint asks for:
   - `EMBEDDER_URL`: the Cloud Run URL from step 1;
   - `EMBEDDER_TOKEN`: the token from step 1;
   - `OPENAI_API_KEY` and `GEMINI_API_KEY`: leave both empty for now. With neither, the service runs in
     evidence-only mode: search with full provenance, no generated answer. The first provider listed in
     `config/service.yaml` whose key is present answers.
3. **Apply.** The first build takes a few minutes. Python 3.12 comes from `.python-version`.
4. Check it: `curl https://<your-service>.onrender.com/api/health`. The `embedder` block should say
   `warm: true` within a minute, with the model the index was built with.

The service allows browser calls only from the origins in `config/service.yaml` (`cors_origins`). The
GitHub Pages origin `https://thomas-amann-ipaustralia.github.io` is already there.

## 3. The front end on GitHub Pages

1. Repository **Settings > Pages > Build and deployment > Source: GitHub Actions**.
2. **Settings > Secrets and variables > Actions**:
   - **Variables** tab: `RENDER_API_URL` = the Render URL from step 2, without a trailing slash;
   - **Secrets** tab: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` from a **read-only** R2
     token (Cloudflare dashboard > R2 > Manage API tokens > Create API token: Object Read only, limited
     to the `econ-knowledge` bucket). The workflow copies the PDFs into the site, checking each one's
     hash, so the page viewer can draw a passage on its page. Without them the site still works; the
     viewer points to the publisher's page instead.
3. **Actions > pages > Run workflow** (it also runs on every push to `main` that changes the site).
4. The site is at `https://thomas-amann-ipaustralia.github.io/Econ/`.

**Publishing the PDFs makes them public.** The owner approved this (D-010): all 24 are IP Australia's
public reports, and the site footer says so and links to them on ipaustralia.gov.au.

## 4. Check it end to end

Open the site. The status chip shows the server waking (up to about a minute on Render's free tier),
then "Evidence only (no model key)". Ask a question: the evidence trail should say "Meaning and keyword
search, combined"; open a passage to see it highlighted on its PDF page. If the trail says "keyword
search only", Render cannot reach the embedder: recheck `EMBEDDER_URL` and `EMBEDDER_TOKEN`.

## Optional: fewer cold starts

Set the repository variable `KEEP_WARM` to `true` to have `.github/workflows/keep-warm.yml` ping the API
every 10 minutes in Canberra business hours (about 220 of Render's 750 free hours a month). GitHub can
delay scheduled runs, so this reduces cold starts rather than removing them.

## Later: model keys

Add `OPENAI_API_KEY` or `GEMINI_API_KEY` in the Render service's **Environment** settings; saving them
redeploys the service with answers turned on. The daily spending cap is `daily_budget_usd` in
`config/service.yaml`.
