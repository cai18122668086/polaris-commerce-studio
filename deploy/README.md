# Polaris internal staging deployment

This deployment profile is for one internal user and has no public domain. It
is not a public production configuration.

The only published socket is `127.0.0.1:8080` on the server. Caddy terminates
the single same-origin HTTP entry point and sends `/api/*` and `/health/*` to
the API; all other requests go to the frontend. PostgreSQL, Redis, MinIO, API,
Celery worker, and outbox dispatcher have no host port mappings.

## Security boundary

This staging profile deliberately uses the backend development identity because
external authentication is not implemented yet. The SSH key and loopback-only
port binding are the authentication and network boundary. Never change the
Caddy mapping to `0.0.0.0`, never expose an internal service port, and never
use this profile as a public website.

Before any public launch, implement and test external authentication, buy and
configure a domain, enable publicly trusted TLS, add abuse controls, and replace
the development identity.

The real environment file must exist only at
`/etc/polaris/polaris.env`, be owned by root, have mode `600`, and never be
committed, copied into the repository, or included in a build context.

## SSH tunnel access

From an authorized Windows workstation:

```powershell
ssh -i "<PATH_TO_PRIVATE_KEY>" -N `
  -L 8080:127.0.0.1:8080 ubuntu@43.129.198.147
```

Keep that terminal open, then visit `http://127.0.0.1:8080`. Each additional
operator should use an individual SSH account and key rather than sharing the
server key.

## First deployment

These commands are documentation for the separately approved deployment phase.
Do not run them while reviewing this asset-only commit.

```bash
sudo install -d -m 0750 -o root -g docker /opt/polaris
sudo install -d -m 0750 -o root -g root /etc/polaris
sudo install -m 0600 -o root -g root \
  deploy/.env.internal.example /etc/polaris/polaris.env
# Edit /etc/polaris/polaris.env locally on the server and replace every marker.

docker compose \
  --env-file /etc/polaris/polaris.env \
  -f deploy/compose.internal.yml \
  config

docker compose \
  --env-file /etc/polaris/polaris.env \
  -f deploy/compose.internal.yml \
  build

docker compose \
  --env-file /etc/polaris/polaris.env \
  -f deploy/compose.internal.yml \
  up -d
```

Compose runs the Alembic `migrate` service before API and workers become
healthy. Do not run schema creation through application startup.

## Upgrade and rollback

Record the last known-good Git commit before every upgrade. Build the candidate
without stopping the current stack, run migrations, then recreate services:

```bash
git fetch --ff-only
git switch --detach <APPROVED_COMMIT>
docker compose --env-file /etc/polaris/polaris.env \
  -f deploy/compose.internal.yml build
docker compose --env-file /etc/polaris/polaris.env \
  -f deploy/compose.internal.yml up -d
```

For rollback, first confirm whether the new migration is backward compatible.
Restore the database backup when it is not. Then switch back to the recorded
commit and rebuild/recreate the stack. Never point a previous application
version at a database schema it cannot understand.

## Backup and restore

Store backups outside Docker volumes and copy them to a separate storage
account or region. A database backup must be taken before every migration:

```bash
umask 077
docker compose --env-file /etc/polaris/polaris.env \
  -f deploy/compose.internal.yml exec -T postgres \
  pg_dump -U polaris -d polaris -Fc > /var/backups/polaris/polaris.dump
```

Restore into an empty, isolated database first and verify row counts and API
readiness before replacing the staging database:

```bash
docker compose --env-file /etc/polaris/polaris.env \
  -f deploy/compose.internal.yml exec -T postgres \
  pg_restore -U polaris -d polaris --clean --if-exists \
  < /var/backups/polaris/polaris.dump
```

Back up the MinIO volume with a versioned object-level copy to the Hong Kong COS
bucket. Test retrieval of both an original upload and a generated image. A
database dump without its corresponding objects is not a complete backup.

## Health and operations

With the SSH tunnel active:

```bash
curl --fail http://127.0.0.1:8080/health/live
curl --fail http://127.0.0.1:8080/health/ready
docker compose --env-file /etc/polaris/polaris.env \
  -f deploy/compose.internal.yml ps
docker compose --env-file /etc/polaris/polaris.env \
  -f deploy/compose.internal.yml logs --since 15m
```

Monitor container health/restarts, worker queue depth, failed jobs, provider
latency and 429 responses, API error rate, PostgreSQL backup age, disk usage,
inode usage, memory, swap, and monthly network traffic. Compose rotates each
container's JSON logs at 20 MB with five retained files.

Rotate the PostgreSQL, Redis, MinIO, access-URL, Tengli, and SSH credentials
individually. Update `/etc/polaris/polaris.env`, recreate only affected
services, verify health, then revoke the previous credential. Never print a
secret in shell history or application logs.
