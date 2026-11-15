# Environments and promotion

SpendWise runs in two separate environments. Every commit on `main` that passes CI goes to
**development** by itself. **Production** changes only when someone promotes, by hand, the exact
commit that development already runs.

| | Development | Production |
|---|---|---|
| URL | <https://spendwise-amyx.onrender.com> | <https://54.79.77.189.nip.io> |
| Provider | Render: one free Docker web service (`render.yaml`) | AWS: one EC2 instance running Docker Compose behind Caddy ([deploy/aws/](../deploy/aws/README.md)) |
| Database | Render PostgreSQL (`spendwise-db`), reachable only from Render | PostgreSQL 18 in a container on the instance, data on the encrypted EBS volume, never published |
| `APP_ENV` | `development` (`render.yaml`) | `production` (`compose.yaml`, `deploy/aws/compose.aws.yaml`) |
| Version | `RENDER_GIT_COMMIT`, set by Render for each deploy | `APP_VERSION`, the SHA the deploy wrapper deploys |
| Deploy | **Automatic** after successful main CI (`autoDeployTrigger: checksPass`) | **Manual**: GitHub Actions, **Promote Development to Production** |
| Costs | free plans only | the existing free-tier instance; nothing added |

Two more values exist for code that isn't deployed: `local` (the backend run from source, and
the local Docker Compose stack) and `test` (the test suite). `local`, `test`, `development` and
`production` are the only values the app accepts. The environment is never guessed from a
hostname, and any other value stops the app at startup.

**Ordinary pushes no longer deploy production.** A push to `main` (a merged pull request) runs CI
and then deploys development only. CI has no deploy job and no OIDC permission at all, and the
production deploy gateway refuses tokens from CI, from pushes and from pull requests.

## The flow

```
pull request ──► CI (backend, backend-postgres, frontend, integration, e2e, "All checks passed")
     │
     ▼ merge
main ──► CI on the push ──► all checks pass
                                 │
                                 ▼
               Render deploys that commit (DEVELOPMENT)
               GET /api/meta → {"environment": "development", "version": "<sha>"}
                                 │      production is unchanged
                                 │
     by hand: Actions ► Promote Development to Production ► Run workflow (main)
                                 │
                                 ▼
 verify             this run is for the head of main (github.sha, never "main")
                    CI's push run for that SHA: completed, success, "All checks passed" success
                    development reports that SHA (waits up to 30 minutes), environment
                    development, /api/health and /api/health/ready ok
                                 │
 deploy             GitHub OIDC token (audience spendwise-deploy, masked, stdin only)
                    POST <PRODUCTION_URL>/_deploy {sha, run_id, run_attempt}
                    the gateway verifies the token: promote-production.yml, workflow_dispatch,
                    main, this SHA and run, used once; the root wrapper deploys the SHA only if
                    it is still the head of main, with APP_VERSION=<sha>; polled every 20 s
                                 │
 verify-production  /api/health and /api/health/ready ok; /api/meta environment production and
                    version <sha>; / serves the app
```

Each step fails the run if its check fails, and production is touched only after every check in
`verify` passed. The workflow is `.github/workflows/promote-production.yml`; the gateway and its
token checks are described in [deploy/aws/README.md](../deploy/aws/README.md#mode-b-github-oidc-deploy-gateway-this-account).

## Promoting

In GitHub:

1. Wait until development runs the commit. CI on `main` must have passed, and Render must have
   deployed it: <https://spendwise-amyx.onrender.com/api/meta> shows its SHA. The workflow also
   waits for this, for up to 30 minutes, so you can start it as soon as CI has passed.
2. **Actions**, then **Promote Development to Production** in the list of workflows.
3. **Run workflow**, leave **Branch: main**, then **Run workflow**.
4. Open the run (named "Promote `<sha>` to production"). It takes about as long as building the
   image on the instance: typically 20 to 45 minutes.

Or from a terminal:

```bash
gh workflow run promote-production.yml --ref main
gh run watch "$(gh run list --workflow promote-production.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
curl -s https://54.79.77.189.nip.io/api/meta          # {"environment":"production","version":"<sha>"}
```

The workflow takes no inputs: it promotes the head of `main` and nothing else. Only one
promotion runs at a time (`concurrency: production-promotion`) and a running one is never
cancelled. A second run waits for the first. GitHub keeps only one waiting run per group, so an
even newer run replaces the waiting one.

When it fails:

| Error | What to do |
|---|---|
| `Promotion runs from main only` | Start it with **Branch: main**. |
| `main is at …` / `main moved on to …` | Someone merged meanwhile. Wait for CI and development, then promote again: only the head of `main` is ever promoted. |
| `No CI run for a push of …` / `CI for … is in_progress` / `(failure)` | Promote only after CI on `main` passed for this commit. Re-run CI if it failed for an unrelated reason. |
| `Development did not report … within 30 minutes` | Render didn't deploy the commit (build failed, or auto-deploy is off). Check the service's Events and Logs on Render. |
| `reports environment 'production', not development` | Render's `APP_ENV` isn't `development` (a Blueprint that wasn't synced): see [Switching to manual promotion](#switching-to-manual-promotion-once). |
| `The deploy gateway reported unauthorized` | The gateway on the instance doesn't trust this workflow yet (still the old `ci.yml` settings), or the run isn't a manual run on `main`. `sudo journalctl -u spendwise-deploy-gateway` names the failing claim. |
| `… is no longer the head of main` (superseded) | The instance refused the commit because `main` moved on. Production is unchanged. Promote again. |
| `busy`, `deploy_failed`, `health_failed`, `timeout` | See [Troubleshooting](../deploy/aws/README.md#troubleshooting). |
| `runs an unknown version` / `runs <other sha>` | The deploy reported success but the app doesn't report the promoted commit. Check the gateway's wrapper is the current one (`install-gateway.sh --verify`, then reinstall). |

## `GET /api/meta`

Public (like the health checks), read-only, and never cached (`Cache-Control: no-store`):

```json
{"environment": "production", "version": "835f9e36979e446878df74d9c9340bbd3ad46922"}
```

- `environment` is `APP_ENV`.
- `version` is the exact commit: `APP_VERSION` if set, else Render's `RENDER_GIT_COMMIT`, else
  `null`. A value that isn't a full 40-character lowercase SHA (`main`, a short SHA, a tag)
  stops the app at startup, without the value appearing in the error.
- Nothing else is exposed: no hostnames, database details, infrastructure IDs, settings or
  secrets.

On AWS the root deploy wrapper (`deploy/aws/gateway/spendwise-deploy-sha`) exports
`APP_VERSION=<the SHA it deploys>` before running `spendwise-deploy`. `compose.yaml` passes it
into the app container. A deploy that bypasses the wrapper (a manual `spendwise-deploy`, or a
new instance's first boot) reports `"version": null` until the next promotion, unless it sets
`APP_VERSION` itself (see [Rollback](#rollback)). The image never contains a version: the same
image could run any commit's configuration, so the version is a run-time setting.

The same two values are ready for telemetry: `Settings.resource_attributes()` in
`backend/app/core/config.py` returns `service.name` (`spendwise`), `deployment.environment`
(`APP_ENV`) and `service.version` (the SHA, when known). Nothing uses it yet; it's there for the
observability work that follows.

## Data isolation

- Development uses only its Render database. `DATABASE_URL` comes from the Blueprint
  (`fromDatabase: spendwise-db`), never a literal URL. `ipAllowList: []` blocks every
  connection from outside Render, including from AWS.
- Production uses only the PostgreSQL container on the instance (`…@db:5432/spendwise`, built
  by `compose.yaml`). It has no published port and the security group opens only 80 and 443.
- They never share a `DATABASE_URL`, nothing copies data between them, and the promotion
  workflow touches no database. Promoting ships code only. Each environment runs its own
  migrations (`alembic upgrade head` at startup) against its own data.
- Tests check this: `test_render_blueprint.py`, `test_aws_templates.py`
  (`test_production_and_development_never_share_a_database`, and the merged AWS Compose
  configuration).

Render's free database expires 30 days after it was created and is then deleted (README,
[Free-tier limits](../README.md#free-tier-limits-read-before-relying-on-it)). That affects
development only.

## Rollback

- **Preferred: revert on `main`.** `git revert <bad commit>`, pull request, merge. CI tests the
  revert, development deploys it, and you promote it like any other commit. Production then
  runs the revert commit, and `/api/meta` says so.
- **The workflow can't promote an older commit.** It promotes only the head of `main`, and the
  instance's wrapper refuses anything else. A re-run of an old promotion fails at "main is at …".
- **Emergency rollback, without CI:** in a Session Manager shell on the instance, as an
  administrator:

  ```bash
  sudo flock -n /run/spendwise-deploy.lock env APP_VERSION=<older sha> spendwise-deploy <older sha>
  ```

  The lock keeps it from overlapping a promotion, and `APP_VERSION` keeps `/api/meta` truthful.
  `main` still holds the bad commit, so follow up with a revert: the next promotion would deploy
  it again.
- **Migrations go forward only.** Startup runs `alembic upgrade head`. If the bad commit added a
  migration, an older image doesn't know the database's newer revision and won't start. Roll
  back such a change with a revert commit that keeps the migration (or adds a new one), not by
  deploying an older SHA.
- **Development can be rolled back on Render** (the service's Deploys, Rollback). It then no
  longer runs the head of `main`, so a promotion waits and fails until development runs `main`
  again.
- A failed promotion leaves production on its previous commit unless the new containers had
  already replaced the old ones. In that case `docker compose up --wait` reports them unhealthy,
  the gateway reports `deploy_failed`, and the fix is a revert, or the emergency rollback above.

## Who can promote

Anyone with write access to the repository can run a workflow by hand, so they can promote. They
can only promote the head of `main`, after it passed CI and runs in development, and branch
protection decides what reaches `main`. To require an approval as well, a GitHub environment
with required reviewers would work. Its jobs get another OIDC subject
(`repo:…:environment:<name>`), though, so the gateway's subject would have to change with it.
That isn't set up.

## Switching to manual promotion (once)

These steps apply this change to the running environments. None of them replaces the instance,
opens a port, touches a database or needs a stack update.

1. **Merge the change.** CI runs on `main` and deploys nothing to production. Render deploys the
   merge commit (`<sha>` below) after CI passed.
2. **Check development.** `curl -s https://spendwise-amyx.onrender.com/api/meta` should show
   `{"environment":"development","version":"<sha>"}`. If `environment` isn't `development`, the
   Blueprint wasn't synced: in Render, sync the Blueprint (Blueprints, the SpendWise Blueprint,
   Manual Sync), or set `APP_ENV=development` on the `spendwise` service (Environment). Render
   keeps the old `ENVIRONMENT=production` variable, which the app ignores; you can delete it.
3. **Update the gateway on the instance.** It still trusts `ci.yml` pushes, so a promotion would
   get `unauthorized` until then. In a Session Manager shell, deploy `<sha>` once by hand (this
   puts the new gateway files into the root-owned checkout) and reinstall the gateway:

   ```bash
   sudo /usr/local/sbin/spendwise-deploy-sha <sha>       # the current head of main
   sudo bash /opt/spendwise/src/deploy/aws/gateway/install-gateway.sh
   sudo bash /opt/spendwise/src/deploy/aws/gateway/install-gateway.sh --verify   # every line "ok"
   ```

   The installer's `--check` output must show
   `workflow_ref  allfocusSS/SpendWise/.github/workflows/promote-production.yml@refs/heads/main`
   and `event_name    workflow_dispatch`. Production now runs `<sha>` and reports
   `"version": null`, because the old wrapper ran that deploy.
4. **Promote** `<sha>` as described in [Promoting](#promoting). This first promotion deploys the
   same commit again through the new path and checks everything, including
   `{"environment":"production","version":"<sha>"}`.

The repository variables stay as they are: `AWS_DEPLOY_MODE=oidc-gateway` (the promotion refuses
to run without it) and `PRODUCTION_URL=https://54.79.77.189.nip.io`.
