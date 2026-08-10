#!/usr/bin/env python3
"""Fail-closed production-auth deployment preflight.

The checker reports variable names and structural failures only. It never prints
secret values or a rendered Compose configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import stat
import sys
from pathlib import Path

from generate_production_env import (
    IMAGE_KEYS,
    INFRA_SECRET_KEYS,
    PROVIDER_KEYS,
    load_env,
)

EXPECTED_SERVICES = {
    "postgres", "redis", "minio", "supertokens", "migrate", "api", "worker",
    "dispatcher", "frontend", "caddy",
}
EXPECTED_NETWORKS = {"edge", "backend", "ingress", "mail-egress", "provider-egress"}
EXPECTED_EXTERNAL_VOLUMES = {
    "postgres_data": "polaris-internal-staging_postgres_data",
    "redis_data": "polaris-internal-staging_redis_data",
    "minio_data": "polaris-internal-staging_minio_data",
}
EXPECTED_SERVICE_VOLUMES = {
    "postgres": "postgres_data:/var/lib/postgresql",
    "redis": "redis_data:/data",
    "minio": "minio_data:/data",
}
EXPECTED_SERVICE_NETWORKS = {
    "postgres": {"backend"},
    "redis": {"backend"},
    "minio": {"backend"},
    "supertokens": {"backend"},
    "migrate": {"backend"},
    "api": {"edge", "backend", "mail-egress"},
    "worker": {"backend", "provider-egress"},
    "dispatcher": {"backend"},
    "frontend": {"edge"},
    "caddy": {"edge", "ingress"},
}
RELEASE_SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST_REFERENCE = re.compile(r"^[a-z0-9][a-z0-9./_-]*(?::[A-Za-z0-9._-]+)?@sha256:[0-9a-f]{64}$")
APP_REFERENCE = re.compile(r"^polaris/(backend|frontend):([0-9a-f]{40})$")
MARKER = re.compile(r"<[^>]+>|replace-with|change-me|dev_only", re.IGNORECASE)
SUPERTOKENS_REFERENCE = (
    "supertokens/supertokens-postgresql:12.0.10@sha256:"
    "4516ec7c00b8fb2a773012694d8ebf03b54799d59cfc974160590f16d235ce72"
)
REQUIRED_ENV_KEYS = {
    "POLARIS_RELEASE_SHA", "POLARIS_BACKEND_IMAGE", "POLARIS_FRONTEND_IMAGE",
    *IMAGE_KEYS, "POLARIS_SUPERTOKENS_IMAGE", *INFRA_SECRET_KEYS,
    "POLARIS_SUPERTOKENS_API_KEY", "POLARIS_AUTH_SMTP_HOST", "POLARIS_AUTH_SMTP_PORT",
    "POLARIS_AUTH_SMTP_USERNAME", "POLARIS_AUTH_SMTP_PASSWORD", "POLARIS_AUTH_SMTP_SECURE",
    "POLARIS_AUTH_EMAIL_FROM_NAME", "POLARIS_AUTH_EMAIL_FROM_ADDRESS", "POLARIS_ACME_EMAIL",
    "POLARIS_S3_BUCKET", *PROVIDER_KEYS,
}
SENSITIVE_MIN_LENGTH = {
    "POLARIS_POSTGRES_PASSWORD": 24,
    "POLARIS_REDIS_PASSWORD": 24,
    "POLARIS_MINIO_ROOT_PASSWORD": 24,
    "POLARIS_ACCESS_URL_SECRET": 32,
    "POLARIS_SUPERTOKENS_API_KEY": 32,
    "POLARIS_AUTH_SMTP_PASSWORD": 8,
}


def parse_mapping_blocks(text: str, heading: str) -> dict[str, str]:
    lines = text.splitlines()
    try:
        start = lines.index(f"{heading}:") + 1
    except ValueError:
        return {}
    result: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[start:]:
        if line and not line.startswith(" "):
            break
        match = re.match(r"^  ([a-z][a-z0-9_-]*):\s*$", line)
        if match:
            current = match.group(1)
            result[current] = [line]
        elif current is not None:
            result[current].append(line)
    return {name: "\n".join(block) for name, block in result.items()}


def service_networks(block: str) -> set[str]:
    inline = re.search(r"^    networks: \[([^]]+)\]$", block, re.MULTILINE)
    if inline:
        return {item.strip() for item in inline.group(1).split(",")}
    lines = block.splitlines()
    try:
        start = lines.index("    networks:") + 1
    except ValueError:
        return set()
    result: set[str] = set()
    for line in lines[start:]:
        match = re.fullmatch(r"      - ([a-z][a-z0-9_-]*)", line)
        if match:
            result.add(match.group(1))
            continue
        if line and not line.startswith("      "):
            break
    return result


def validate_env(env: dict[str, str], base: dict[str, str] | None = None) -> list[str]:
    errors: list[str] = []
    missing = sorted(key for key in REQUIRED_ENV_KEYS if key not in env)
    if missing:
        errors.append("missing environment variables: " + ", ".join(missing))
    for key in sorted(REQUIRED_ENV_KEYS & env.keys()):
        if MARKER.search(env[key]):
            errors.append(f"{key} still contains a template or development marker")
    sha = env.get("POLARIS_RELEASE_SHA", "")
    if not RELEASE_SHA.fullmatch(sha):
        errors.append("POLARIS_RELEASE_SHA must be a 40-character lowercase Git SHA")
    for key in ("POLARIS_BACKEND_IMAGE", "POLARIS_FRONTEND_IMAGE"):
        value = env.get(key, "")
        match = APP_REFERENCE.fullmatch(value)
        if not match or match.group(2) != sha:
            errors.append(f"{key} must be an immutable application image matching POLARIS_RELEASE_SHA")
    for key in (*IMAGE_KEYS, "POLARIS_SUPERTOKENS_IMAGE"):
        if not DIGEST_REFERENCE.fullmatch(env.get(key, "")):
            errors.append(f"{key} must be pinned by sha256 digest")
    if env.get("POLARIS_SUPERTOKENS_IMAGE") != SUPERTOKENS_REFERENCE:
        errors.append("POLARIS_SUPERTOKENS_IMAGE must be the approved Core v12.0.10 linux/amd64 manifest")
    for key, minimum in SENSITIVE_MIN_LENGTH.items():
        if len(env.get(key, "")) < minimum:
            errors.append(f"{key} is shorter than the production minimum")
    if not re.fullmatch(r"[A-Za-z0-9=-]+", env.get("POLARIS_SUPERTOKENS_API_KEY", "")):
        errors.append("POLARIS_SUPERTOKENS_API_KEY contains characters rejected by Core v12.0.10")
    if env.get("POLARIS_AUTH_EMAIL_FROM_ADDRESS") != "no-reply@mail.tengliapi.xyz":
        errors.append("POLARIS_AUTH_EMAIL_FROM_ADDRESS must be no-reply@mail.tengliapi.xyz")
    if "@" not in env.get("POLARIS_ACME_EMAIL", ""):
        errors.append("POLARIS_ACME_EMAIL must be a valid contact email")
    try:
        port = int(env.get("POLARIS_AUTH_SMTP_PORT", ""))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        errors.append("POLARIS_AUTH_SMTP_PORT must be between 1 and 65535")
    if env.get("POLARIS_AUTH_SMTP_SECURE", "").lower() not in {"true", "false"}:
        errors.append("POLARIS_AUTH_SMTP_SECURE must be true or false")
    if base is not None:
        changed = [key for key in PROVIDER_KEYS if key in base and env.get(key) != base.get(key)]
        if changed:
            errors.append("Provider settings changed during auth cutover: " + ", ".join(changed))
    return errors


def validate_compose(compose: str) -> list[str]:
    errors: list[str] = []
    services = parse_mapping_blocks(compose, "services")
    if set(services) != EXPECTED_SERVICES:
        errors.append("production Compose service set is not the approved set")
    networks = parse_mapping_blocks(compose, "networks")
    if set(networks) != EXPECTED_NETWORKS:
        errors.append("production Compose network set is not the approved set")
    for service, expected in EXPECTED_SERVICE_NETWORKS.items():
        if service in services and service_networks(services[service]) != expected:
            errors.append(f"{service} has an unexpected network attachment")
    for service, block in services.items():
        if service != "caddy" and re.search(r"^    ports:", block, re.MULTILINE):
            errors.append(f"{service} must not publish host ports")
    caddy = services.get("caddy", "")
    for port in ('"80:80"', '"443:443"', '"443:443/udp"'):
        if port not in caddy:
            errors.append(f"caddy is missing production port {port}")
    supertokens = services.get("supertokens", "")
    for required in ("API_KEYS:", "POSTGRESQL_CONNECTION_URI:", "http://127.0.0.1:3567/hello"):
        if required not in supertokens:
            errors.append(f"supertokens service is missing {required}")
    if "POLARIS_ENVIRONMENT: production" not in compose or "POLARIS_AUTH_MODE: external" not in compose:
        errors.append("production Compose must force production/external authentication")
    if "POLARIS_SUPERTOKENS_COOKIE_SECURE: \"true\"" not in compose:
        errors.append("production Compose must force Secure authentication cookies")
    if 'POLARIS_CORS_ORIGINS: \'["https://www.tengliapi.xyz"]\'' not in compose:
        errors.append("production Compose must use the exact same-origin CORS allowlist")
    volumes = parse_mapping_blocks(compose, "volumes")
    for volume, expected_name in EXPECTED_EXTERNAL_VOLUMES.items():
        block = volumes.get(volume, "")
        if not re.search(
            rf"^    name: {re.escape(expected_name)}$", block, re.MULTILINE
        ):
            errors.append(f"{volume} must reuse the approved existing data volume")
        if not re.search(r"^    external: true$", block, re.MULTILINE):
            errors.append(f"{volume} must remain an external volume")
    for service, expected_mount in EXPECTED_SERVICE_VOLUMES.items():
        block = services.get(service, "")
        if not re.search(
            rf"^      - {re.escape(expected_mount)}$", block, re.MULTILINE
        ):
            errors.append(f"{service} must mount the approved existing data volume")
    return errors


def dockerfile_copy_sources(dockerfile: str) -> list[tuple[str, list[str], str]]:
    logical_lines: list[str] = []
    pending = ""
    for raw_line in dockerfile.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        pending = f"{pending} {stripped}".strip()
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        logical_lines.append(pending)
        pending = ""
    if pending:
        logical_lines.append(pending)

    result: list[tuple[str, list[str], str]] = []
    for line in logical_lines:
        match = re.match(r"^(COPY|ADD)\s+(.+)$", line, re.IGNORECASE)
        if not match:
            continue
        instruction = match.group(1).upper()
        payload = match.group(2).strip()
        while payload.startswith("--"):
            flag, separator, remainder = payload.partition(" ")
            if not separator or "=" not in flag:
                break
            payload = remainder.lstrip()
        try:
            arguments = json.loads(payload) if payload.startswith("[") else shlex.split(payload)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(arguments, list) or len(arguments) < 2:
            continue
        result.append((instruction, [str(item) for item in arguments[:-1]], str(arguments[-1])))
    return result


def normalize_docker_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.rstrip("/")


def validate_backend_dockerfile(dockerfile: str) -> list[str]:
    errors: list[str] = []
    owner_source = "backend/scripts/assign_workspace_owner.py"
    owner_destination = "scripts/assign_workspace_owner.py"
    owner_packaged = False
    for instruction, sources, destination in dockerfile_copy_sources(dockerfile):
        normalized_destination = normalize_docker_path(destination)
        for source in sources:
            normalized_source = normalize_docker_path(source)
            if (
                instruction == "COPY"
                and normalized_source == owner_source
                and normalized_destination == owner_destination
            ):
                owner_packaged = True
            if normalized_source == "backend/scripts" or (
                normalized_source.startswith("backend/scripts/")
                and normalized_source != owner_source
            ):
                errors.append("backend image must not package other operator scripts")
    if not owner_packaged:
        errors.append(
            "backend image must package the explicit workspace owner assignment script"
        )
    return errors


def validate_caddy(caddy: str) -> list[str]:
    errors: list[str] = []
    for required in (
        "www.tengliapi.xyz {", "reverse_proxy api:8000",
        "reverse_proxy frontend:3000", "Strict-Transport-Security",
    ):
        if required not in caddy:
            errors.append(f"production Caddyfile is missing {required}")
    if "auto_https off" in caddy:
        errors.append("production Caddyfile must not disable automatic HTTPS")
    if "\ntengliapi.xyz {" in caddy:
        errors.append("production Caddyfile must not claim the apex domain before its DNS is approved")
    if ":8080" in caddy:
        errors.append("production Caddyfile must not use the internal-only :8080 site")
    return errors


def validate_mode(path: Path) -> list[str]:
    if os.name == "nt":
        return []
    mode = stat.S_IMODE(path.stat().st_mode)
    return [] if mode == 0o600 else [f"env file mode must be 0600, found {mode:04o}"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--base-env", type=Path)
    parser.add_argument("--compose-file", type=Path, default=Path(__file__).with_name("compose.production.yml"))
    parser.add_argument("--caddyfile", type=Path, default=Path(__file__).with_name("Caddyfile.production"))
    parser.add_argument(
        "--backend-dockerfile",
        type=Path,
        default=Path(__file__).with_name("backend.Dockerfile"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        env = load_env(args.env_file)
        base = load_env(args.base_env) if args.base_env else None
        errors = validate_env(env, base)
        errors.extend(validate_mode(args.env_file))
        errors.extend(validate_compose(args.compose_file.read_text(encoding="utf-8")))
        errors.extend(validate_caddy(args.caddyfile.read_text(encoding="utf-8")))
        errors.extend(
            validate_backend_dockerfile(
                args.backend_dockerfile.read_text(encoding="utf-8")
            )
        )
    except (OSError, ValueError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(f"BLOCKED: {error}", file=sys.stderr)
        return 2
    print("PASS: production authentication deployment preflight completed without displaying secrets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
