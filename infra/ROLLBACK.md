# Rollback runbook — PayNexus V2.1 (`foundry-v2`)

A short, honest runbook for the one scenario CI can't protect against: a deploy that
passes tests and pushes cleanly but is wrong in production (a bad env var, a real-world
edge case the test suite doesn't cover, a Foundry/Azure-side regression). This is a
manual procedure — nothing here is automated, and that's a real, current gap (see
"What this doesn't cover" below), not an oversight.

## Backend (`paynexus-api-v2`)

The backend deploys via a Docker Hub webhook: every push to `foundry-v2` that passes
`test-backend` builds and pushes `ramya192/paynexus-backend:v2-latest` *and*
`:v2-<git-sha>`, and Docker Hub's webhook triggers the App Service to pull whichever tag
the webhook names — in practice `:v2-latest`, since that's the tag the webhook is scoped
to (see `deploy-v2.yml`'s comment on `deploy-backend`).

**To roll back:**
1. Find the last-known-good SHA — either from the GitHub Actions run history (each
   successful `deploy-backend` run names the SHA it built), or from Docker Hub's tag list
   for `ramya192/paynexus-backend` (each push leaves a `:v2-<sha>` tag, so nothing is
   overwritten except `:v2-latest` itself).
2. Re-tag that known-good image as `:v2-latest` and push it — this re-triggers the same
   webhook the normal deploy path uses, so no App Service config changes:
   ```bash
   docker pull ramya192/paynexus-backend:v2-<known-good-sha>
   docker tag ramya192/paynexus-backend:v2-<known-good-sha> ramya192/paynexus-backend:v2-latest
   docker push ramya192/paynexus-backend:v2-latest
   ```
3. Confirm: `curl https://paynexus-api-v2.azurewebsites.net/health` — watch the response
   for a minute or two; App Service's own pull-and-restart isn't instant.

**Faster, if you don't want to touch Docker Hub tags at all:** point the App Service
directly at the known-good SHA tag instead of `:v2-latest` (bypasses the webhook
entirely, takes effect within the same command):
```bash
az webapp config container set --name paynexus-api-v2 --resource-group paynexus-rg \
  --docker-custom-image-name ramya192/paynexus-backend:v2-<known-good-sha>
```
Remember this leaves the App Service pinned off `:v2-latest` — the *next* normal push to
`foundry-v2` won't reach it until you either revert this command or push a new `:v2-<sha>`
and repeat it. Treat it as a stop-the-bleeding step, not a substitute for actually fixing
forward.

## Frontend (`paynexus-web-v2`, Azure Static Web Apps)

Azure Static Web Apps keeps each deployment's build as a distinct "environment" — no
manual re-tagging needed.
1. Azure Portal → the Static Web App resource → **Environments** (or **Deployment
   history**) → find the last-known-good deployment.
2. Simplest real option: re-run that specific past GitHub Actions workflow run (Actions
   tab → the known-good run → "Re-run all jobs") — rebuilds and re-deploys the exact same
   commit's frontend.

## What this doesn't cover (honest gaps, not hidden)

- **No automated rollback trigger.** Nothing watches post-deploy health and rolls back on
  its own — a human has to notice the problem and run the steps above. A real
  next step would be a deployment slot with a health-check gate, which needs a paid App
  Service tier (see the F1-tier cost decision in `paynexus-v2-pending-items` memory) — a
  known, deliberate trade-off, not an oversight.
- **No database rollback story.** Alembic migrations are forward-only here; a bad
  migration needs a hand-written down-migration or a manual fix, same as most small
  projects without a dedicated DBA process. Out of scope for this runbook.
- **Not tested against a real incident yet.** These steps are correct by inspection
  (they use documented `az`/`docker` behavior) but haven't been exercised end-to-end
  against an actual bad deploy — worth a deliberate dry run once, the same "verify live,
  don't trust it because it reads right" discipline the rest of this project follows.
