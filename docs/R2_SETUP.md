# Publishing county worlds to Cloudflare R2 — one-time setup (D-031)

The build workflow (`.github/workflows/build-counties.yml`) builds each county on a GitHub
runner and uploads it to an R2 bucket. The public site links to the viewers served from
that bucket. Setup takes about 15 minutes and is done once. Labels in the Cloudflare
dashboard change from time to time; the steps below describe what to look for.

## Current setup (2026-11-15)
Bucket `ruralsim-data` (Standard, ENAM), public development URL
`https://pub-b414cd9251804d11871e4bec734e096e.r2.dev`.

## 1. Create the bucket
In the Cloudflare dashboard, open **R2 Object Storage** and create a bucket named
`ruralsim-data` (any name works; it goes in `R2_BUCKET` below). Default location is fine.

## 2. Make it publicly readable
In the bucket's **Settings**, under public access, either:
- **Custom domain (production):** connect `data.ruralsim.io`. This needs the `ruralsim.io`
  zone to be on Cloudflare DNS. If ruralsim.io's DNS is managed elsewhere (for example at
  Vercel), add the zone to Cloudflare first, or use the next option for now.
- **Public development URL (testing):** enable the `r2.dev` URL. Cloudflare rate-limits it
  and does not recommend it for production; it is fine for the canary run.

The public base URL from this step (e.g. `https://data.ruralsim.io`) is `RURALSIM_DATA_BASE`.

## 3. Create an API token for the uploads
Under R2's API token management, create a token with **Object Read & Write** permission,
limited to the `ruralsim-data` bucket. Copy the **Access Key ID** and **Secret Access Key**
(the secret is shown once) and note your **Account ID** from the R2 overview page.

## 4. Give GitHub the credentials
In the GitHub repo: **Settings → Secrets and variables → Actions**.
- Secrets: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`
- The bucket name is not secret and is written into the workflow file (`R2_BUCKET: ruralsim-data`);
  change it there if you use a different bucket.

Never commit these values or paste them into an issue, pull request or chat.

## 5. Tell the site where the data lives
In the Vercel project `ruralsim`: **Settings → Environment Variables**, add
`RURALSIM_DATA_BASE` with the same URL for Production and Preview. The site build reads
`<RURALSIM_DATA_BASE>/worlds/index.json` and links every published county from the
National page. Without it the site builds exactly as before (pilots only).

## 6. First run
GitHub → **Actions → Build county worlds → Run workflow**, counties `48301` (Loving TX),
publish on. When it finishes, `<RURALSIM_DATA_BASE>/worlds/index.json` lists the county
and its viewer is at `<RURALSIM_DATA_BASE>/worlds/48301_loving_tx/current/viewer/index.html`
(R2 public URLs do not serve `index.html` for a bare folder path; always name the file).
Redeploy the site (or push any commit) to pick up the new link.

## 7. Optional: redeploy the site automatically after each build
Without this, the site links newly built counties only at its next deploy (any merge to
`main`, or Redeploy in Vercel). To make every build run refresh the site:
1. Vercel → project `ruralsim` → **Settings → Git → Deploy Hooks**: create a hook named
   `county-builds` for branch `main`. Copy the URL it shows.
2. GitHub → repo **Settings → Secrets and variables → Actions → New repository secret**:
   name `VERCEL_DEPLOY_HOOK`, value the hook URL. Treat it as a secret: anyone with it can
   trigger deploys.
The workflow's last step then triggers a production redeploy after rebuilding the index.

## 8. OSM extract mirror (D-036)
The plan job copies each Geofabrik state extract a batch needs into the bucket under
`osm/` (the `.pbf` and Geofabrik's `.md5`), once and one at a time, and the county jobs
read them from there with the same R2 credentials. Nothing to set up: it uses the three
secrets above. Copies older than 7 days are refreshed on the next run that needs them;
a full national set is about 10 GB (~$0.15 a month). To force a refresh, delete the
object in the Cloudflare dashboard (R2 → `ruralsim-data` → `osm/`).
