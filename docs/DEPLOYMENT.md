# Deployment guide

This guide deploys MapleLaunch on free tiers: **Render** for hosting and **Supabase** for Postgres, file storage and
authentication. It takes about 20 minutes the first time.

There are two independent environments built from the same code:

| | Demo | Production |
|---|---|---|
| Blueprint file | `render.yaml` | `render.production.yaml` |
| Services | `maplelaunch-api`, `maplelaunch-mock`, `maplelaunch-web` | `maplelaunch-prod-api`, `maplelaunch-prod-providers`, `maplelaunch-prod-web` |
| Mode | `APP_MODE=demo` | `APP_MODE=production` |
| What users see | One-click demo accounts, sample documents, scenario lab, reset button | Self-signup, no demo tooling |
| Supabase project | Its own | Its own (never share a database between the two) |

Deploy the demo first. Production is optional and uses the same steps with a second Supabase project.

---

## 1. Before you start

You need accounts on:

* [GitHub](https://github.com), with this repository pushed to it
* [Render](https://render.com) (sign in with GitHub)
* [Supabase](https://supabase.com)
* [Groq](https://console.groq.com/keys) and/or [Google AI Studio](https://aistudio.google.com/apikey) for LLM keys
* [Resend](https://resend.com) (optional, for email notifications)

No credit card is needed for any of them.

## 2. Create the Supabase project

1. Supabase dashboard → **New project**. Pick a region close to your Render region (for example Mumbai or
   Singapore). Save the **database password** you choose; you need it in step 2.3.
2. When the project is ready, open **Project Settings → API Keys** and copy:
   * **Project URL**, for example `https://abcdefghijklmnop.supabase.co`
   * **Publishable key** (`sb_publishable_...`; older projects call it the *anon* key)
   * **Secret key** (`sb_secret_...`; older projects call it the *service_role* key). Treat it like a password.
3. Click **Connect** (top bar) → **Session pooler** and copy the connection string. It looks like:

   ```
   postgresql://postgres.abcdefghijklmnop:YOUR-PASSWORD@aws-0-ap-south-1.pooler.supabase.com:5432/postgres
   ```

   Replace `YOUR-PASSWORD` with the database password. If the password contains characters such as `@`, `#`, `/`
   or `%`, URL-encode them (`@` becomes `%40`, `#` becomes `%23`). Use the **Session pooler on port 5432**, not the
   direct connection: Render cannot reach Supabase's IPv6-only direct host, and the transaction pooler (port 6543)
   breaks the session-level advisory locks that keep two workers from running the same application at once.

You don't need to create tables, buckets or users. On first start the API creates its tables, the private
`documents` storage bucket and the accounts (demo accounts in demo mode, the admin in production mode).

> **JWT signing keys:** new Supabase projects sign tokens with asymmetric keys, which the API verifies through the
> project's public JWKS endpoint, so nothing else is needed. Only if your project still uses the legacy shared JWT
> secret, copy it from **Project Settings → JWT Keys** into `SUPABASE_JWT_SECRET`.

## 3. Get the LLM keys

* **Groq** (primary): [console.groq.com/keys](https://console.groq.com/keys) → *Create API key* (`gsk_...`).
  Optional: put extra keys from other Groq projects in `GROQ_API_KEYS`, comma-separated. Groq limits are per
  organization, so keys from the same organization share one quota.
* **Gemini** (fallback): [aistudio.google.com/apikey](https://aistudio.google.com/apikey) → *Create API key*. The
  app tries several Gemini models in turn (`GEMINI_MODELS`), because each model has its own free daily quota.

One provider is enough to run; both give the best resilience. Without any key, the platform still works with the
offline sample reader and the rules engine, but uploaded real documents can't be read.

## 4. Optional: Resend for email

[resend.com](https://resend.com) → *API Keys* → create a key (`re_...`). Without a verified domain, Resend only
delivers to the email address you signed up with, so emails to the demo accounts (`@example.com`) are skipped and
recorded as failed in the notification log. The in-app inbox always works.

## 5. Deploy the demo on Render

1. Render dashboard → **New → Blueprint** → connect the GitHub repository.
2. Blueprint path: leave the default `render.yaml`. Render lists three services: `maplelaunch-api`,
   `maplelaunch-mock` and `maplelaunch-web`.
3. Render asks for the values marked `sync: false`:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` (asked twice: API and mock services) | Session pooler string from step 2.3, the same value for both |
   | `SUPABASE_URL` | Project URL |
   | `SUPABASE_ANON_KEY` | Publishable (anon) key |
   | `SUPABASE_SERVICE_ROLE_KEY` | Secret (service_role) key |
   | `SUPABASE_JWT_SECRET` | Leave empty unless your project uses the legacy JWT secret |
   | `GROQ_API_KEY` | Groq key |
   | `GROQ_API_KEYS` | Optional extra Groq keys, comma-separated, or empty |
   | `GEMINI_API_KEY` | Gemini key |
   | `RESEND_API_KEY` | Optional, or empty |

   Everything else is set for you: `APP_SECRET`, `ENCRYPTION_KEY`, `BLIND_INDEX_KEY`, `WEBHOOK_SECRET` and
   `PROVIDER_ADMIN_TOKEN` are generated randomly, and the URLs between the three services are wired automatically.
4. Click **Apply**. The first build takes 5 to 10 minutes. The static site finishes first; the API is ready when its
   health check turns green.

### Check that it works

1. Open `https://maplelaunch-api.onrender.com/healthz`. Expect `{"ok":true,"mode":"demo","llm":true,"auth":"supabase"}`.
2. Open the web URL (`https://maplelaunch-web.onrender.com`) → **Open the ops console** → **Scenario lab** → run
   **Happy path**. Within about 30 seconds it should reach *Live* with a merchant ID.
3. In Supabase → **Table editor**, you should see the `applications`, `audit_log` and `checkpoints` tables, and in
   **Storage** a private `documents` bucket.

If the service names were already taken on Render, your URLs get a suffix. Use the URLs shown in the dashboard.

## 6. Deploy production (optional)

1. Create a **second** Supabase project and collect the same values as in step 2.
2. Render → **New → Blueprint** → same repository → **Blueprint path: `render.production.yaml`**.
3. Fill in the same variables as above, plus:

   | Variable | Value |
   |---|---|
   | `ADMIN_EMAIL` | Email for the first admin account |
   | `ADMIN_PASSWORD` | A strong password (at least 8 characters) |

4. After deploy, `/healthz` should report `"mode":"production"`. Sign in with the admin account. Merchants create
   their own accounts through **Apply as a merchant**.

Production refuses to start if any secret is still a development default or the encryption keys are missing. The
Render log then names the missing setting.

## 7. Region: keep Render next to the database

The production Blueprint puts all services in **Singapore**, next to a Supabase project in **Mumbai (ap-south-1)**. In
the demo Blueprint the `region:` line is commented out, because the demo was first created in Oregon (Render's default)
and Render cannot change an existing service's region; uncomment it when you create the demo services from scratch. Every API
request makes a few database round trips, so distance matters: with Render in Oregon and Supabase in Mumbai, a
simple request takes about 1 second instead of roughly 0.2 seconds.

If your Supabase project is in another region, change `region:` in the Blueprint to the closest Render region
(`oregon`, `ohio`, `virginia`, `frankfurt` or `singapore`). Render cannot move an existing service: to change the
region, delete the three services and apply the Blueprint again (same names, so the URLs stay the same). The secrets
are regenerated, so also clear the old data (Scenario lab → **Reset demo data** before deleting, or a fresh Supabase
project).

## 8. Keep the demo awake (optional)

Free Render web services sleep after about 15 minutes without traffic, and the first request after that takes 30 to
60 seconds. The repository includes `.github/workflows/keepalive.yml`, which pings the API every 10 minutes from
08:30 to 20:30 IST; while awake, the API keeps the provider service warm. That fits two services inside Render's
750 free instance-hours a month.

GitHub → repository → **Settings → Secrets and variables → Actions → Variables** → **New repository variable**:
`API_URL` = `https://maplelaunch-api.onrender.com`.

Also note that Supabase pauses free projects after 7 days without activity; the keepalive pings prevent that too.

## 9. Day-2 operations

* **Reset the demo:** sign in as the demo admin → Scenario lab → **Reset demo data**. It deletes all applications
  and restores the default policy (as a new version, so the history stays). Users are kept.
* **Change a secret:** edit it in Render → service → **Environment**, then redeploy. Do not change
  `ENCRYPTION_KEY` or `BLIND_INDEX_KEY` on an environment that has data: existing encrypted fields could no longer be
  read, and duplicate detection would stop matching.
* **Failed background jobs:** Scenario lab (demo) or Background jobs (production) lists jobs that failed every retry,
  with a **Replay** button.
* **Logs:** Render → service → **Logs**. Logs are structured JSON, and PAN, GSTIN, account numbers and emails are
  redacted.

## 10. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| API or mock crashes with `No module named 'pgserver'` or `DATABASE_URL is 'pgserver'` | `DATABASE_URL` is missing or still the local-development value. Set it on **both** `maplelaunch-api` and `maplelaunch-mock` (Render → service → **Environment**) to the Supabase Session pooler URL, then save (it redeploys). |
| Webhooks never arrive, CORS errors, or sign-in fails after deploy | A local `.env` was pasted into Render and overwrote deploy settings. Delete `PUBLIC_API_URL`, `PROVIDERS_BASE_URL` and `WEB_ORIGIN` if they say `localhost` (the Blueprint wires them), and make sure `AUTH_MODE` and `STORAGE_MODE` are `supabase`. |
| API deploy fails with `connection refused` or `Network is unreachable` | `DATABASE_URL` uses the direct host. Use the Session pooler string (port 5432). |
| `password authentication failed` | Wrong database password, or special characters not URL-encoded. |
| Port 6543 in `DATABASE_URL` | That is the transaction pooler, which breaks per-application locking. Use the Session pooler (port 5432). |
| `Refusing to start in production mode: ...` | A production secret is missing or still a dev default. Set the named variable. |
| Sign-in says `Incorrect email or password` for demo accounts | The API couldn't create users: check `SUPABASE_SERVICE_ROLE_KEY` is the **secret** key, not the publishable one. |
| Every page feels slow (about 1 s per click) | Render and Supabase are far apart. See section 7. |
| Web app loads but every request fails | The API is still waking up (wait a minute), or `WEB_ORIGIN` doesn't match the site URL (CORS). Redeploy the API after renaming services. |
| Documents show "We couldn't read this automatically" | Every LLM provider failed or hit its quota. Check the keys; the application still continues and routes to a human. |
| Checks stay *Requested* for a long time | The provider service was asleep. It retries webhook delivery; the timeout job then retries the check. |
| Emails not arriving | Expected without a verified Resend domain, except to your own Resend address. |
