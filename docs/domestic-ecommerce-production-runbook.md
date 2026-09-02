# Domestic ecommerce production runbook

This runbook is intentionally a deployment checklist, not a claim that the
local workstation has a production PostgreSQL, Redis, object store, browser
node, or external-auth environment.

## 1. Gate the release

1. Use the repository `D:\Projects\polaris-commerce-studio-model-pose-entrypoints`
   and the intended release branch.
2. Review `git status --short --branch` and preserve unrelated user changes.
3. Use `deploy/production.env.example` as the complete non-secret configuration
   contract and populate the server-managed environment through the deployment
   platform's secret manager. `deploy/.env.production.example` is the separate
   release-image/server-generator template. Do not commit a populated copy of
   either file or copy developer browser profiles.
4. Confirm `POLARIS_TASK_DISPATCHER=celery`,
   `POLARIS_AUTO_CREATE_SCHEMA=false`, `POLARIS_STORAGE_BACKEND=s3`,
   `POLARIS_S3_AUTO_CREATE_BUCKET=false`, and
   `POLARIS_ECOMMERCE_PROXY_ENABLED=false`.
5. Keep Amazon disabled and planned. A production release must not turn on an
   Amazon provider as a side effect of domestic ecommerce deployment.

## 2. Provision dependencies before application startup

- PostgreSQL: create the database, least-privilege application user, TLS
  policy, connection limits, and backups.
- Redis: create separate broker/result databases or ACLs and configure a
  persistent policy appropriate for the deployment.
- S3-compatible storage: create the `polaris-assets` bucket, block public
  access, configure lifecycle/retention, and grant only the application
  object permissions it needs.
- Browser profile volume: provision an encrypted, access-controlled durable
  volume shared by `api` and `crawl-worker` only. One account must map to one
  profile and one active lease.
- Browser runtime: build `backend/Dockerfile.crawl-worker`, install Chromium,
  and verify the image contains a working browser executable.

## 3. Apply and verify migrations

Run from `backend` with the deployment environment loaded:

```powershell
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini current
python -m alembic -c alembic.ini heads
```

The expected head for this release is `20260901_0015`. For a disposable
PostgreSQL validation database, run the optional test only after setting both
`POLARIS_POSTGRES_E2E_URL` and
`POLARIS_POSTGRES_E2E_ALLOW_MUTATION=true`.

## 4. Build and start in dependency order

The API and all crawl services use the immutable browser-enabled image referenced
by `POLARIS_CRAWL_WORKER_IMAGE`. Build it once before startup; the production
cutover itself must use the already-built image with `--no-build --pull never`.

```powershell
docker compose --env-file deploy/production.env build --pull=false api
docker compose --env-file deploy/production.env up -d --build postgres redis minio migrate
docker compose --env-file deploy/production.env up -d --no-build --pull never api worker crawl-worker crawl-maintenance dispatcher
```

Use the production orchestrator's native health and restart policies. Do not
expose PostgreSQL, Redis, or MinIO admin endpoints publicly.

## 5. Health and queue checks

Run the secret-free health smoke first. It only performs GET requests and does
not create crawl jobs, access browser profiles, or print response bodies:

```powershell
python deploy/post_deploy_smoke.py --base-url https://api.example.com
```

The command must report `PASS` for all three endpoints before continuing. A
nonzero exit code is a release blocker. Do not treat a successful liveness
check alone as a deployment success.

For a manual record of the raw health responses, run the same three requests
after the script passes:

```powershell
curl.exe -f https://api.example.com/health/live
curl.exe -f https://api.example.com/health/ready
curl.exe -f https://api.example.com/health/ecommerce
```

`/health/ready` must report `database`, `task_broker`, `object_storage`, and
external `authentication` as `ok`. `/health/ecommerce` reports only aggregate
crawl counts, active/expired leases, and oldest queued age; it must not contain
URLs, cookies, profile paths, or provider secrets.

Verify Celery queue separation:

```powershell
docker compose exec worker celery -A app.celery_app:celery_app inspect active
# The normal worker must consume `default`; crawl-worker must consume `crawl`.
```

## 6. Controlled browser and platform verification

For each of Taobao/Tmall, 1688, JD/JD Global Purchase, and Pinduoduo:

1. Use a dedicated non-production test account and a fresh account-owned
   profile on the persistent volume.
2. Complete manual login only through the approved operations workflow.
3. Run one low-rate static and one browser crawl with no proxy variables.
4. Capture request route/egress evidence without storing cookies or tokens.
5. Test cancellation, login-required state, browser crash, worker restart, and
   profile lease fencing.

Do not modify the existing platform parser logic as part of deployment
verification. Amazon remains `enabled=false`, `status=planned`.

## 7. Backup, alerting, and rollback

Before external traffic:

- Run and record PostgreSQL backup/restore and migration rollback drills.
- Define alerts for readiness failure, queue age, expired leases, task failure
  rate, login/risk-control rate, orphan asset purge errors, and storage growth.
- Configure tenant/API rate limits and durable quota ledgers, then test both
  rejection and recovery behavior.
- Keep the previous image and migration rollback plan available. Roll back by
  deploying a known version through the release system; do not use destructive
  working-tree Git commands on the server.

## 8. Evidence to retain

Retain the release id, image digests, migration output, health responses,
backup/restore evidence, browser crash/restart evidence, egress evidence,
operator identity, approvals, and any account-login audit records. Redact
cookies, access tokens, passwords, signed URLs, and full product URLs where
not required.
