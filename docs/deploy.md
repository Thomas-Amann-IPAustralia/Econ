# Deploying

Three pieces, each on its own host (D-003). Set them up in this order: the embedder first (the API needs
its URL), then the API (the front end needs its URL), then the front end.

```
GitHub Pages (front end, PDFs)  ──►  Render (API: search, answer, check)  ──►  Cloud Run (embedding model)
                                                 └──►  OpenAI or Gemini (answers, when a key is set)
```

Nothing here has been deployed yet: the build session had no GCP credentials or Render API key.

## 1. The embedder on Google Cloud Run

You need a Google Cloud project with billing enabled (Cloud Run's free tier is per billing account; check
[Cloud Run pricing](https://cloud.google.com/run/pricing) for how it applies in your region). The commands
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

# Build (from the repository root) and deploy.
IMAGE=$REGION-docker.pkg.dev/$PROJECT/econ/embedder:$(git rev-parse --short=12 HEAD)
gcloud builds submit --config deploy/embedder/cloudbuild.yaml --substitutions _IMAGE=$IMAGE .
gcloud run deploy econ-embedder --region $REGION --image $IMAGE \
  --cpu 1 --memory 2Gi --cpu-boost --min-instances 0 --max-instances 2 --concurrency 8 --timeout 60 \
  --allow-unauthenticated --set-secrets EMBEDDER_TOKEN=econ-embedder-token:latest

URL=$(gcloud run services describe econ-embedder --region $REGION --format='value(status.url)')
curl -s -H "Authorization: Bearer $TOKEN" $URL/health     # shows the model, its revision and hash
```

- `--allow-unauthenticated` lets Render reach the service without a Google identity; the bearer token
  keeps everyone else out. The stronger alternative, IAM-authenticated calls, would need a Google
  service-account key stored on Render.
- `--max-instances 2` caps what a flood of requests could cost.
- Sizing, measured locally: the service holds about 720 MB with the model loaded; a warm query takes
  about 45 ms on one vCPU; loading the model takes about 2 s, on top of Cloud Run's own start-up.
- To redeploy from GitHub instead, set up Workload Identity Federation and the repository variables
  named at the top of `.github/workflows/embedder.yml`, then run that workflow by hand.

## 2. The API on Render

1. Render dashboard > **New > Blueprint** > this repository (branch `main` once merged). It reads
   `render.yaml`: a free Python web service in Singapore.
2. Set the environment variables the blueprint asks for:
   - `EMBEDDER_URL`: the Cloud Run URL from step 1;
   - `EMBEDDER_TOKEN`: the token from step 1;
   - `OPENAI_API_KEY` **or** `GEMINI_API_KEY`: optional. With neither, the service runs in evidence-only
     mode: search with full provenance, no generated answer. The first provider listed in
     `config/service.yaml` whose key is present answers.
3. Check it: `curl https://<your-service>.onrender.com/api/health`. The `embedder` block should say
   `warm: true` within a minute, with the model the index was built with.

The service allows browser calls only from the origins in `config/service.yaml` (`cors_origins`). The
GitHub Pages origin `https://thomas-amann-ipaustralia.github.io` is already there.

## 3. The front end on GitHub Pages

1. Repository **Settings > Pages > Source: GitHub Actions**.
2. **Settings > Secrets and variables > Actions**:
   - variable `RENDER_API_URL`: the Render URL from step 2, without a trailing slash;
   - secrets `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`: a **read-only** R2 token for
     the `econ-knowledge` bucket. The workflow copies the PDFs into the site so the page viewer can draw a
     passage on its page. Without them the site still works; the viewer links out instead.
3. Run the **pages** workflow (Actions > pages > Run workflow), or push to `main`.
4. The site is at `https://thomas-amann-ipaustralia.github.io/Econ/`.

**Publishing the PDFs makes them public.** All 24 are IP Australia publications under CC BY 4.0 as far as
the parse could tell (`library/index/docs.json` records each licence), but confirm before adding the R2
secrets.

## Optional: fewer cold starts

Set the repository variable `KEEP_WARM` to `true` to have `.github/workflows/keep-warm.yml` ping the API
every 10 minutes in Canberra business hours (about 220 of Render's 750 free hours a month). GitHub can
delay scheduled runs, so this reduces cold starts rather than removing them.
