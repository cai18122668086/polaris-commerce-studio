# Polaris internal staging

This profile is a single-internal-user environment reached only through an SSH
tunnel. It is not a public production profile. The only host socket is Caddy on
`127.0.0.1:8080`. Database, object storage and application traffic stay on
internal networks. Only the worker attaches to the dedicated provider-egress
network; the frontend never receives Provider configuration.

Execution defaults to the mock runner. The API and worker can use the shared
Tengli adapter only after daily and monthly cost limits plus a daily request
limit are approved in the server-local environment. A real job reserves its
maximum retry exposure before queueing, and planner/image execution fails closed
without that durable reservation. Internal S3 downloads always use the
same-origin content proxy; browsers never receive the `minio:9000` endpoint.

## Non-negotiable boundaries

- Never publish Caddy on `0.0.0.0`, public IPv6, or a non-loopback interface.
- Never publish PostgreSQL, Redis, MinIO, API, worker, dispatcher, or frontend.
- Never attach the default `edge` or `backend` network to external egress.
- Never put the server environment file, SSH keys, or credentials in Git,
  images, build contexts, logs, command output, or support bundles.
- Never use this development identity profile as a public site.
- Do not enable transport-upgrade policy on this HTTP-only staging endpoint.
- Do not enable the real Provider runner without approved daily/monthly cost and daily request caps.

The real environment file exists only as `/etc/polaris/polaris.env`, owned by
`root:root` with mode `0600`. Create it in place on the server with `sudoedit`;
do not copy a populated file from a workstation.

## Source and supply-chain gate

The approved deployment commit must have exactly one parent, and that parent
must be the approved product commit. Reject merge commits, unrelated ancestry,
evidence-only ancestry, a dirty worktree, or changes outside `.dockerignore`
and `deploy/**`.

Run the dependency-free source gate from the repository root:

```text
python deploy/preflight.py --mode source
python -m unittest discover -s deploy/tests -v
```

Source validation checks the service set, default-mock runner selection,
worker-only Provider egress, loopback binding, image indirection, resource and
log limits, hardening, CSP, security headers, and secret placeholders.

The product supplies `backend/requirements.lock` with exact versions and real
SHA-256 hashes. The backend image performs exactly one dependency installation
with `--require-hashes` and `--only-binary=:all:`. It does not install the local
project, invoke a build backend, copy `pyproject.toml`, or depend on setuptools
from the base image. `/app` is the working directory, so the copied `app/**`
package directly resolves the Uvicorn, Celery, and dispatcher modules; copied
`alembic.ini`, `migrations/**`, `app/skill_manifests/**`, and the byte-locked
`skill_sources/**` runtime bundle supply migration and integrity data at their
runtime paths. API and worker share
`POLARIS_XINGHE_SKILL_ROOT=/app/skill_sources/xinghe-ecommerce-detail`; the
Provider gate still verifies the complete manifest before any external request.

Node dependencies use the committed `package-lock.json` and
`npm ci --ignore-scripts --no-audit --fund=false`. The verified `build` and
`start` scripts apply the required Vinext production patch themselves, so
dependency lifecycle scripts remain disabled during image installation.

## Immutable image gate

Every third-party image is a required `name@sha256:<64 lowercase hex>` value.
No Dockerfile has a default base image, and Compose uses `pull_policy: never`.
The example values are intentionally invalid markers.

Before a deployment, with separately approved registry and server access:

1. Resolve and review the exact `linux/amd64` digest for Python, Node,
   PostgreSQL, Redis, MinIO, and Caddy.
2. Pull them during the authorized acquisition window, or load an approved
   offline archive with its checksum.
3. Record tag, manifest digest, platform digest, image ID, source, acquisition
   time, SBOM, and scan result.
4. Build backend and frontend images with tags exactly equal to the approved
   40-hex release commit. Record their image IDs and content digests.
5. Keep the last known-good application images locally. Do not prune them
   during the release window.

Missing images must block `up`; do not let deployment implicitly contact a
registry.

## Resource ceiling

These are safety ceilings, not capacity claims:

<!-- preflight:resource-budget:start -->
| Compose service | Memory MiB | CPUs | PIDs |
| --- | ---: | ---: | ---: |
| `postgres` | 512 | 0.50 | 256 |
| `redis` | 112 | 0.25 | 128 |
| `minio` | 384 | 0.50 | 256 |
| `api` | 384 | 0.50 | 256 |
| `worker` | 768 | 0.75 | 512 |
| `dispatcher` | 192 | 0.25 | 128 |
| `frontend` | 384 | 0.25 | 256 |
| `caddy` | 128 | 0.20 | 128 |
| **Long-running total** | **2864** | **3.20** | **1920** |
| `migrate` | 512 | 0.50 | 256 |
<!-- preflight:resource-budget:end -->

Source preflight compares every service memory, CPU, and PID value plus all
long-running totals against `compose.internal.yml`; any drift blocks release.

The long-running total must not exceed 70% of confirmed host memory or 80% of
confirmed host CPUs. This table therefore still requires an authorized host
inventory; it is not permission to deploy on an unknown machine.

All services use `json-file` rotation at 20 MiB with five files. Application,
frontend, migration, and Caddy containers drop all capabilities and use
read-only root filesystems with explicit tmpfs mounts. Database services retain
only their named writable data volumes and upstream entrypoint behavior; record
their effective user and capabilities after the approved image acquisition.

## Authorized server preflight

SSH access, registry access, image pulls, builds, firewall changes, backups,
migrations, container starts, and public-port changes each require new user
authorization. Tightening public ports 80/443 is recommended for this internal
profile, but it is a separate cloud-firewall decision. Port 22 remains limited
to approved user IPs.

Before any build or start, record:

- Docker and Compose versions and architecture;
- CPU, memory, swap, Docker root filesystem, backup filesystem, free bytes,
  and free inode percentage;
- existing containers, networks, volumes, images, build cache, and project
  resources;
- listeners and cloud/host firewall state;
- the candidate image size, paired-backup size, and last known-good images;
- the absence or approved presence of the fixed Caddy image.

Free inode percentage must be at least 10%. Free disk must be at least:

```text
max(20 GiB, 2 * candidate-image-size + paired-backup-size + 10 GiB)
```

Do not use automatic image or volume pruning to satisfy this gate.

After creating `/etc/polaris/polaris.env` in place, run the deployment gate. It
names invalid variables but never prints values:

```text
python deploy/preflight.py \
  --mode deployment \
  --env-file /etc/polaris/polaris.env \
  --host-memory-mib <CONFIRMED_MIB> \
  --host-cpus <CONFIRMED_CPUS> \
  --free-disk-mib <CONFIRMED_MIB> \
  --free-inode-percent <CONFIRMED_PERCENT> \
  --candidate-images-mib <MEASURED_MIB> \
  --paired-backup-mib <MEASURED_MIB>
```

Any `BLOCKED` result stops the release.

## Compose and Caddy validation

Static Compose expansion is required before build or start:

```text
docker compose \
  --env-file /etc/polaris/polaris.env \
  -f deploy/compose.internal.yml \
  config
```

Inspect the rendered output without copying it off the server. Confirm exactly
nine services, migrate and dispatcher pinned to mock, API and worker using the
shared default-mock Provider settings, only worker on provider-egress, and only
`127.0.0.1:8080:8080` published.

The server is not assumed to have a Caddy CLI or cached image. After the fixed
Caddy image has been acquired under explicit authorization, validate with that
exact Compose image reference:

```text
CADDY_IMAGE="$(sudo sed -n 's/^POLARIS_CADDY_IMAGE=//p' \
  /etc/polaris/polaris.env)"
test -n "$CADDY_IMAGE"

docker run --rm \
  --network none \
  --read-only \
  --user 10001:10001 \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --tmpfs /config:uid=10001,gid=10001,mode=0700 \
  --tmpfs /data:uid=10001,gid=10001,mode=0700 \
  --mount type=bind,src="$(pwd)/deploy/Caddyfile",dst=/etc/caddy/Caddyfile,readonly \
  "$CADDY_IMAGE" \
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

Do not substitute a host CLI, a different tag, or another digest. A nonzero
validation result blocks deployment. This repository only documents the
command; running it requires the later server/container authorization.

The CSP denies all external resource and connection origins. Vinext's current
same-origin inline bootstrap is permitted with `script-src 'unsafe-inline'`;
same-origin scripts remain allowed. If the frontend removes this requirement,
tighten the policy in a separately tested change.

## Paired backup gate

Before every migration of a nonempty environment, quiesce new writes and create
one timestamped backup set containing:

- a PostgreSQL custom-format dump;
- a complete MinIO object/data snapshot taken after writers are stopped;
- UTC timestamp, release SHA, schema revision, image IDs, object count, row
  counts, byte sizes, and SHA-256 checksums for both artifacts.

Copy the pair to separately approved storage. A database-only or object-only
backup is incomplete. Redis is a queue/cache, not the source of record; drain
or account for pending outbox work before backup.

One approved implementation is to stop API, worker, and dispatcher, create the
database dump, stop MinIO, copy its named-volume data from the stopped
container, checksum both artifacts, then resume only after the pair and
manifest are complete. Do not expose a database or MinIO port for backup.

Every backup method must first pass a restore drill in a new temporary Compose
project with new database and object volumes. Restore the dump into the empty
temporary database, restore objects into the temporary MinIO volume, and verify
checksums, row/object counts, schema revision, API readiness, and a mock job.
Never point `pg_restore --clean` at the active `polaris` database. Never reuse
the active project name or active volumes for a restore drill.

## Approved build and release sequence

The following phase is documentation, not authorization:

1. Reconfirm commit lineage, clean worktree, permissions, capacity, ports,
   firewall decision, immutable image inventory, SBOM/scan evidence, and paired
   backup/restore evidence.
2. Run source and deployment preflight; require PASS.
3. Run `docker compose config`; require PASS.
4. Run same-digest Caddy validation; require PASS.
5. Build immutable application images in the approved network window. A missing
   dependency lock, digest, or image blocks the build.
6. Review candidate migrations and record current/head revisions, expected
   locks and duration, and backward-compatibility classification.
7. Start with `--no-build --pull never`. Migration must complete successfully
   before API, worker, or dispatcher can start.
8. Require all long-running services healthy and no restart loop.
9. Confirm the only listener is loopback 8080 and all non-Caddy services have
   no host port.
10. Through the SSH tunnel, run live/ready checks and complete both workflows in
    mock mode. After recurring beta limits are explicitly approved, set the
    daily/monthly cost caps and daily request cap, switch only the server-local
    runner to `tengli`, and restart API and worker. Confirm a bounded front-end
    job reserves quota once, successful pages are not re-billed, downloads use
    the same-origin proxy, and local-edit reports zero changed pixels outside
    the authority mask.
11. Observe logs, restarts, queue depth, API errors, disk, inodes, memory, and
    CPU for the approved observation window before accepting the release.

Migration failure, an unhealthy service, a restart loop, an unexpected
listener, unapproved Provider execution, unexpected egress, or capacity breach
stops the release and triggers rollback.

## SSH tunnel

From an authorized workstation:

```text
ssh -i "<APPROVED_PRIVATE_KEY_PATH>" -N -L 8080:127.0.0.1:8080 <APPROVED_USER>@<APPROVED_SERVER>
```

Visit `http://127.0.0.1:8080` while the tunnel is open. Use individual SSH
accounts and keys; never share a private key.

## Rollback

Before release, preserve the previous Compose assets, immutable application
image references, image IDs, schema revision, and paired backup manifest.

If the new schema is backward compatible, stop new work and switch back to the
retained application image references with `--no-build --pull never`; do not
rebuild the old release.

If the schema is not backward compatible, stop API, worker, and dispatcher,
keep the active data untouched, and restore the paired PostgreSQL and object
snapshot into an isolated project. Verify it fully, then switch according to a
separately approved recovery plan. Never point an old application at a schema
it cannot understand, never blindly run `alembic downgrade`, and never delete
new volumes, images, or backup sets without separate destructive-action
authorization.

Record the rollback trigger, timestamps, image IDs, schema decision, restored
manifest, verification results, and final listener/health state.
