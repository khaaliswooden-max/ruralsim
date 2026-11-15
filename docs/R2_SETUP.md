# Publishing county worlds to Cloudflare R2 — one-time setup (D-031)

The build workflow (`.github/workflows/build-counties.yml`) builds each county on a GitHub
runner and uploads it to an R2 bucket. The public site links to the viewers served from
that bucket. Setup takes about 15 minutes and is done once. Labels in the Cloudflare
dashboard change from time to time; the steps below describe what to look for.

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
- Variables: `R2_BUCKET` = `ruralsim-data`, `RURALSIM_DATA_BASE` = the URL from step 2

Never commit these values or paste them into an issue, pull request or chat.

## 5. Tell the site where the data lives
In the Vercel project `ruralsim`: **Settings → Environment Variables**, add
`RURALSIM_DATA_BASE` with the same URL for Production and Preview. The site build reads
`<RURALSIM_DATA_BASE>/worlds/index.json` and links every published county from the
National page. Without it the site builds exactly as before (pilots only).

## 6. First run
GitHub → **Actions → Build county worlds → Run workflow**, counties `48301` (Loving TX),
publish on. When it finishes, `<RURALSIM_DATA_BASE>/worlds/index.json` lists the county
and its viewer is at `<RURALSIM_DATA_BASE>/worlds/48301_loving_tx/current/viewer/`.
Redeploy the site (or push any commit) to pick up the new link.
