#!/usr/bin/env python3
"""Fail-closed static and deployment preflight for internal staging.

This script uses only the Python standard library. It never prints environment
values, so deployment checks can safely name a failing variable without
disclosing its content.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path

EXPECTED_SERVICES = {
    "postgres",
    "redis",
    "minio",
    "migrate",
    "api",
    "worker",
    "dispatcher",
    "frontend",
    "caddy",
}
LONG_RUNNING_SERVICES = EXPECTED_SERVICES - {"migrate"}
MOCK_SERVICES = {"migrate", "api", "worker", "dispatcher"}
THIRD_PARTY_IMAGE_KEYS = {
    "POLARIS_PYTHON_BASE_IMAGE",
    "POLARIS_NODE_BASE_IMAGE",
    "POLARIS_POSTGRES_IMAGE",
    "POLARIS_REDIS_IMAGE",
    "POLARIS_MINIO_IMAGE",
    "POLARIS_CADDY_IMAGE",
}
APPLICATION_IMAGE_KEYS = {
    "POLARIS_BACKEND_IMAGE",
    "POLARIS_FRONTEND_IMAGE",
}
SENSITIVE_KEYS = {
    "POLARIS_POSTGRES_PASSWORD",
    "POLARIS_REDIS_PASSWORD",
    "POLARIS_MINIO_ROOT_USER",
    "POLARIS_MINIO_ROOT_PASSWORD",
    "POLARIS_ACCESS_URL_SECRET",
}
FORBIDDEN_PROVIDER_TOKEN = "".join(chr(value) for value in (116, 101, 110, 103, 108, 105))
DIGEST_REFERENCE = re.compile(
    r"^[a-z0-9][a-z0-9./_-]*(?::[A-Za-z0-9._-]+)?@sha256:([0-9a-f]{64})$"
)
RELEASE_SHA = re.compile(r"^[0-9a-f]{40}$")
APPLICATION_REFERENCE = re.compile(r"^[a-z0-9][a-z0-9./_-]*:([0-9a-f]{40})$")
REQUIRED_RUNTIME_PACKAGES = {"alembic", "celery", "uvicorn"}
NPM_LIFECYCLE_SCRIPTS = {
    "preinstall",
    "install",
    "postinstall",
    "prepare",
    "prepublish",
    "prepublishonly",
    "prepack",
    "postpack",
    "dependencies",
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_services(compose: str) -> dict[str, str]:
    lines = compose.splitlines()
    try:
        start = lines.index("services:") + 1
    except ValueError:
        return {}
    services: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[start:]:
        if line and not line.startswith(" "):
            break
        match = re.match(r"^  ([a-z][a-z0-9_-]*):\s*$", line)
        if match:
            current = match.group(1)
            services[current] = [line]
        elif current is not None:
            services[current].append(line)
    return {name: "\n".join(block) for name, block in services.items()}


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in read_text(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("environment file contains a non-assignment line")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def memory_mib(value: str) -> int:
    match = re.fullmatch(r"([0-9]+)([mMgG])", value.strip())
    if not match:
        raise ValueError(f"unsupported memory limit format: {value}")
    amount = int(match.group(1))
    return amount if match.group(2).lower() == "m" else amount * 1024


def service_resources(
    services: dict[str, str],
) -> dict[str, tuple[int, float, int]]:
    resources: dict[str, tuple[int, float, int]] = {}
    for name in EXPECTED_SERVICES:
        block = services.get(name, "")
        memory_match = re.search(r"(?m)^    mem_limit:\s*(\S+)\s*$", block)
        cpu_match = re.search(r'(?m)^    cpus:\s*"?([0-9.]+)"?\s*$', block)
        pids_match = re.search(r"(?m)^    pids_limit:\s*([0-9]+)\s*$", block)
        if memory_match and cpu_match and pids_match:
            resources[name] = (
                memory_mib(memory_match.group(1)),
                float(cpu_match.group(1)),
                int(pids_match.group(1)),
            )
    return resources


def resource_totals(services: dict[str, str]) -> tuple[int, float]:
    resources = service_resources(services)
    missing = EXPECTED_SERVICES - set(resources)
    if missing:
        raise ValueError(
            "cannot total resources with incomplete services: "
            + ", ".join(sorted(missing))
        )
    total_memory = sum(resources[name][0] for name in LONG_RUNNING_SERVICES)
    total_cpus = sum(resources[name][1] for name in LONG_RUNNING_SERVICES)
    return total_memory, total_cpus


def validate_resource_documentation(
    readme: str,
    services: dict[str, str],
    errors: list[str],
) -> None:
    marker_start = "<!-- preflight:resource-budget:start -->"
    marker_end = "<!-- preflight:resource-budget:end -->"
    if readme.count(marker_start) != 1 or readme.count(marker_end) != 1:
        errors.append("README resource budget markers are missing or duplicated")
        return
    table = readme.split(marker_start, 1)[1].split(marker_end, 1)[0]
    resources = service_resources(services)
    if set(resources) != EXPECTED_SERVICES:
        errors.append("Compose resources cannot be compared with README")
        return
    for name in sorted(EXPECTED_SERVICES):
        memory, cpus, pids = resources[name]
        expected_row = f"| `{name}` | {memory} | {cpus:.2f} | {pids} |"
        if table.count(expected_row) != 1:
            errors.append(f"README resource row does not match Compose for {name}")
    total_memory = sum(resources[name][0] for name in LONG_RUNNING_SERVICES)
    total_cpus = sum(resources[name][1] for name in LONG_RUNNING_SERVICES)
    total_pids = sum(resources[name][2] for name in LONG_RUNNING_SERVICES)
    expected_total = (
        "| **Long-running total** | "
        f"**{total_memory}** | **{total_cpus:.2f}** | **{total_pids}** |"
    )
    if table.count(expected_total) != 1:
        errors.append("README long-running resource total does not match Compose")


def dockerfile_instructions(dockerfile: str) -> list[tuple[str, str]]:
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
    instructions: list[tuple[str, str]] = []
    for line in logical_lines:
        parts = line.split(None, 1)
        instructions.append((parts[0].upper(), parts[1] if len(parts) == 2 else ""))
    return instructions


def command_tokens(command: str) -> list[str]:
    if command.lstrip().startswith("["):
        try:
            value = json.loads(command)
        except ValueError:
            return []
        return [str(token) for token in value] if isinstance(value, list) else []
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return []


def npm_scripts_from_tokens(tokens: list[str]) -> list[str]:
    scripts: list[str] = []
    lowered = [token.lower() for token in tokens]
    separators = {"&&", "||", ";", "|"}
    executables = {"npm", "npm.cmd", "npm.exe"}
    for index, token in enumerate(lowered):
        executable = token.replace("\\", "/").rsplit("/", 1)[-1]
        if executable not in executables:
            continue
        end = index + 1
        while end < len(lowered):
            candidate = lowered[end].replace("\\", "/").rsplit("/", 1)[-1]
            if lowered[end] in separators or candidate in executables:
                break
            end += 1
        segment = lowered[index + 1 : end]
        run_index = next(
            (
                offset
                for offset, candidate in enumerate(segment)
                if candidate in {"run", "run-script"}
            ),
            None,
        )
        if run_index is None:
            continue
        script = next(
            (
                candidate
                for candidate in segment[run_index + 1 :]
                if not candidate.startswith("-")
            ),
            "<dynamic>",
        )
        scripts.append(script)
    return scripts


def raw_command_tokens(command: str) -> list[str]:
    """Lex raw RUN text without trusting outer-shell quoting boundaries."""

    return re.findall(
        r"&&|\|\||[;|]|[A-Za-z0-9_.:@/\\-]+",
        command,
        flags=re.IGNORECASE,
    )


def npm_run_scripts(dockerfile: str) -> tuple[list[str], list[str]]:
    raw_scripts: list[str] = []
    token_scripts: list[str] = []
    for instruction, command in dockerfile_instructions(dockerfile):
        if instruction != "RUN":
            continue
        raw_scripts.extend(npm_scripts_from_tokens(raw_command_tokens(command)))
        token_scripts.extend(npm_scripts_from_tokens(command_tokens(command)))
    return raw_scripts, token_scripts


def validate_source(repo_root: Path) -> tuple[list[str], tuple[int, float]]:
    errors: list[str] = []
    deploy = repo_root / "deploy"
    required = {
        ".env.internal.example",
        "Caddyfile",
        "README.md",
        "backend.Dockerfile",
        "compose.internal.yml",
        "frontend.Dockerfile",
    }
    missing = sorted(name for name in required if not (deploy / name).is_file())
    if missing:
        errors.append(f"missing deployment files: {', '.join(missing)}")
        return errors, (0, 0.0)

    forbidden_compose = sorted(
        path.name
        for path in deploy.glob("compose*.yml")
        if path.name != "compose.internal.yml"
    )
    if forbidden_compose:
        errors.append("real-provider or alternate compose files are not allowed")

    scanned_paths = [deploy / name for name in required]
    scanned_text = "\n".join(read_text(path) for path in scanned_paths).lower()
    if FORBIDDEN_PROVIDER_TOKEN in scanned_text:
        errors.append("deployment assets contain a forbidden provider name")

    compose = read_text(deploy / "compose.internal.yml")
    services = parse_services(compose)
    if set(services) != EXPECTED_SERVICES:
        errors.append(
            "service set must be exactly: " + ", ".join(sorted(EXPECTED_SERVICES))
        )

    runner_values = re.findall(r"POLARIS_TASK_RUNNER:\s*([A-Za-z0-9_-]+)", compose)
    if runner_values != ["mock", "mock", "mock", "mock"]:
        errors.append("the four backend execution paths must be explicitly mock")
    for name in MOCK_SERVICES:
        if "POLARIS_TASK_RUNNER: mock" not in services.get(name, ""):
            errors.append(f"{name} is not explicitly pinned to the mock runner")

    if compose.count("\n    ports:") != 1:
        errors.append("exactly one service may declare host ports")
    if '"127.0.0.1:8080:8080"' not in services.get("caddy", ""):
        errors.append("Caddy must be the sole 127.0.0.1:8080 publisher")
    for name, block in services.items():
        if name != "caddy" and "\n    ports:" in block:
            errors.append(f"{name} must not publish a host port")

    try:
        network_section = compose.split("\nnetworks:\n", 1)[1].split(
            "\nvolumes:\n", 1
        )[0]
    except IndexError:
        network_section = ""
    for network in ("edge", "backend"):
        pattern = rf"(?ms)^  {network}:\s*\n(?:(?:    ).*\n)*?    internal:\s*true\s*$"
        if not re.search(pattern, network_section):
            errors.append(f"{network} network must be internal")

    image_lines = re.findall(r"(?m)^\s+image:\s*(.+?)\s*$", compose)
    if len(image_lines) != len(EXPECTED_SERVICES):
        errors.append("each service must declare one immutable image reference")
    for image in image_lines:
        if not re.fullmatch(r"\$\{POLARIS_[A-Z0-9_]+_IMAGE:\?[^}]+\}", image):
            errors.append("compose image references must be required environment variables")
            break

    for name, block in services.items():
        for key in ("mem_limit:", "cpus:", "pids_limit:"):
            if key not in block:
                errors.append(f"{name} is missing {key[:-1]}")
        if "<<: *service-security" not in block:
            errors.append(f"{name} is missing the shared security/logging policy")
        if "pull_policy: never" not in block:
            errors.append(f"{name} must refuse implicit image pulls")
        if name in LONG_RUNNING_SERVICES:
            if "healthcheck:" not in block:
                errors.append(f"{name} is missing a healthcheck")
            if "restart: unless-stopped" not in block:
                errors.append(f"{name} is missing the restart policy")

    for name in ("migrate", "api", "worker", "dispatcher"):
        block = services.get(name, "")
        for requirement in ("user: \"10001:10001\"", "read_only: true", "cap_drop:"):
            if requirement not in block:
                errors.append(f"{name} is missing hardened application isolation")
                break
    for name in ("frontend", "caddy"):
        block = services.get(name, "")
        for requirement in ("read_only: true", "cap_drop:", "tmpfs:"):
            if requirement not in block:
                errors.append(f"{name} is missing hardened runtime isolation")
                break

    caddy_block = services.get("caddy", "")
    if "http://127.0.0.1:8080/health/ready" not in caddy_block:
        errors.append("Caddy healthcheck must use API readiness")
    if "condition: service_healthy" not in caddy_block:
        errors.append("Caddy must wait for healthy upstreams")

    caddyfile = read_text(deploy / "Caddyfile")
    hsts_name = "strict" + "-transport-security"
    if hsts_name in caddyfile.lower() or "upgrade-insecure-requests" in caddyfile.lower():
        errors.append("HTTP staging must not enable transport-upgrade headers or CSP")
    required_headers = (
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Permissions-Policy",
    )
    for header in required_headers:
        if header not in caddyfile:
            errors.append(f"Caddyfile is missing {header}")
    csp_match = re.search(r'Content-Security-Policy "([^"]+)"', caddyfile)
    if not csp_match:
        errors.append("Caddyfile is missing a parseable CSP")
    else:
        csp = csp_match.group(1)
        for directive in (
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline'",
            "connect-src 'self'",
            "frame-ancestors 'none'",
            "object-src 'none'",
        ):
            if directive not in csp:
                errors.append(f"CSP is missing required directive: {directive}")
        if "http:" in csp or "https:" in csp:
            errors.append("CSP must not allow external HTTP origins")

    for dockerfile_name, arg_name, allowed_stages in (
        ("backend.Dockerfile", "POLARIS_PYTHON_BASE_IMAGE", set()),
        ("frontend.Dockerfile", "POLARIS_NODE_BASE_IMAGE", {"dependencies"}),
    ):
        dockerfile = read_text(deploy / dockerfile_name)
        if f"ARG {arg_name}" not in dockerfile:
            errors.append(f"{dockerfile_name} is missing required base image ARG")
        from_lines = re.findall(r"(?m)^FROM\s+(\S+)", dockerfile)
        allowed_from = {f"${{{arg_name}}}"} | allowed_stages
        if not from_lines or any(line not in allowed_from for line in from_lines):
            errors.append(f"{dockerfile_name} contains a non-ARG base image")
        if re.search(rf"(?m)^ARG {arg_name}=", dockerfile):
            errors.append(f"{dockerfile_name} must not default its base image")

    backend_dockerfile = read_text(deploy / "backend.Dockerfile")
    if "backend/requirements.lock" not in backend_dockerfile:
        errors.append("backend image must require the product dependency lock")
    if "PIP_REQUIRE_HASHES=1" not in backend_dockerfile:
        errors.append("backend dependency installation must require hashes")
    if "PIP_REQUIRE_HASHES=0" in backend_dockerfile:
        errors.append("backend image must never disable pip hash mode")
    pip_install_lines = [
        line.strip()
        for line in backend_dockerfile.splitlines()
        if re.search(r"\b(?:python\s+-m\s+)?pip\s+install\b", line)
    ]
    required_pip_install = (
        "RUN python -m pip install --require-hashes "
        "--only-binary=:all: -r requirements.lock"
    )
    if pip_install_lines != [required_pip_install]:
        errors.append(
            "backend image must have exactly one hash-locked, binary-only pip install"
        )
    forbidden_pip_patterns = (
        r"\bpip\s+install\b[^\n]*(?:^|\s)\.(?:\s|$)",
        r"(?:^|\s)(?:-e|--editable)(?:\s|$)",
        r"git\+",
        r"https?://",
        r"\s@\s",
    )
    for pattern in forbidden_pip_patterns:
        if re.search(pattern, backend_dockerfile, flags=re.IGNORECASE):
            errors.append("backend image contains a forbidden project/VCS/URL pip install")
            break
    for forbidden_copy in ("backend/pyproject.toml", "backend/README.md"):
        if forbidden_copy in backend_dockerfile:
            errors.append("backend runtime image must not copy build metadata")
            break
    for required_copy in (
        "COPY backend/alembic.ini ./",
        "COPY backend/app ./app",
        "COPY backend/migrations ./migrations",
    ):
        if required_copy not in backend_dockerfile:
            errors.append(f"backend runtime image is missing: {required_copy}")

    frontend_dockerfile = read_text(deploy / "frontend.Dockerfile")
    npm_install_lines = [
        line.strip()
        for line in frontend_dockerfile.splitlines()
        if re.search(r"\bnpm\s+(?:ci|install)\b", line)
    ]
    required_npm_ci = "RUN npm ci --ignore-scripts --no-audit --fund=false"
    if npm_install_lines != [required_npm_ci]:
        errors.append(
            "frontend image must use exactly one npm ci with --ignore-scripts"
        )
    raw_run_scripts, token_run_scripts = npm_run_scripts(frontend_dockerfile)
    run_scripts = raw_run_scripts + token_run_scripts
    lifecycle_scripts = [
        script for script in run_scripts if script in NPM_LIFECYCLE_SCRIPTS
    ]
    if lifecycle_scripts:
        errors.append(
            "frontend Dockerfile RUN must not invoke npm lifecycle scripts: "
            + ", ".join(sorted(set(lifecycle_scripts)))
        )
    if raw_run_scripts != ["build"]:
        errors.append(
            "frontend Dockerfile raw RUN text may invoke exactly one npm run build"
        )
    if any(script != "build" for script in token_run_scripts):
        errors.append("frontend Dockerfile tokenized RUN may invoke only npm run build")
    try:
        package = json.loads(read_text(repo_root / "package.json"))
        scripts = package.get("scripts", {})
    except (OSError, ValueError, AttributeError):
        scripts = {}
        errors.append("package.json scripts cannot be validated")
    patch_script = "node build/patch-vinext-production.mjs"
    for script_name in ("build", "start"):
        script = scripts.get(script_name, "") if isinstance(scripts, dict) else ""
        if patch_script not in script:
            errors.append(
                f"package.json {script_name} must apply the verified Vinext patch"
            )

    example = parse_env(deploy / ".env.internal.example")
    for key in SENSITIVE_KEYS:
        value = example.get(key, "")
        if not (value.startswith("<") and value.endswith(">")):
            errors.append(f"example value for {key} must remain an unusable marker")
    for key in THIRD_PARTY_IMAGE_KEYS | APPLICATION_IMAGE_KEYS | {"POLARIS_RELEASE_SHA"}:
        value = example.get(key, "")
        if not (value.startswith("<") or "<" in value):
            errors.append(f"example value for {key} must contain an obvious marker")

    dockerignore = read_text(repo_root / ".dockerignore")
    for pattern in (".env", "**/.env", "*.pem", "*.key"):
        if pattern not in dockerignore:
            errors.append(f".dockerignore is missing secret exclusion {pattern}")

    try:
        totals = resource_totals(services)
    except ValueError as exc:
        errors.append(str(exc))
        totals = (0, 0.0)
    validate_resource_documentation(
        read_text(deploy / "README.md"),
        services,
        errors,
    )
    return errors, totals


def lock_blockers(repo_root: Path) -> list[str]:
    lock_path = repo_root / "backend" / "requirements.lock"
    if not lock_path.is_file():
        return ["backend/requirements.lock is absent"]
    content = read_text(lock_path)
    blockers: list[str] = []
    requirements: dict[str, list[str]] = {}
    current_name: str | None = None
    active_lines = [
        line
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    active_text = "\n".join(active_lines)
    forbidden_patterns = (
        r"(?:^|\s)(?:-e|--editable)(?:\s|$)",
        r"git\+",
        r"https?://",
        r"\s@\s",
        r"--(?:extra-)?index-url",
    )
    if any(
        re.search(pattern, active_text, flags=re.IGNORECASE)
        for pattern in forbidden_patterns
    ):
        blockers.append("backend/requirements.lock contains editable, VCS, URL, or index input")

    for line in active_lines:
        if not line[0].isspace():
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s\\]+)\s+\\", line)
            if not match:
                blockers.append(
                    "backend/requirements.lock contains a non-exact requirement"
                )
                current_name = None
                continue
            current_name = match.group(1).lower().replace("_", "-")
            requirements[current_name] = []
            continue
        hash_match = re.fullmatch(
            r"\s+--hash=sha256:([0-9a-f]{64})(?:\s+\\)?", line
        )
        if not hash_match or current_name is None:
            blockers.append(
                "backend/requirements.lock contains an unrecognized continuation"
            )
            continue
        digest = hash_match.group(1)
        if len(set(digest)) == 1:
            blockers.append(
                f"backend/requirements.lock has a sentinel hash for {current_name}"
            )
        requirements[current_name].append(digest)

    if not requirements:
        blockers.append("backend/requirements.lock has no exact requirements")
    for name, hashes in requirements.items():
        if not hashes:
            blockers.append(f"backend/requirements.lock has no sha256 hash for {name}")
    missing_runtime = sorted(REQUIRED_RUNTIME_PACKAGES - set(requirements))
    if missing_runtime:
        blockers.append(
            "backend/requirements.lock is missing runtime packages: "
            + ", ".join(missing_runtime)
        )
    return list(dict.fromkeys(blockers))


def validate_digest_reference(key: str, value: str, errors: list[str]) -> None:
    match = DIGEST_REFERENCE.fullmatch(value)
    if not match:
        errors.append(f"{key} must be an approved name@sha256 reference")
        return
    digest = match.group(1)
    if len(set(digest)) == 1:
        errors.append(f"{key} contains a sentinel digest")


def validate_deployment(
    repo_root: Path,
    env_file: Path | None,
    host_memory_mib: int | None,
    host_cpus: float | None,
    free_disk_mib: int | None,
    free_inode_percent: float | None,
    candidate_images_mib: int | None,
    paired_backup_mib: int | None,
) -> tuple[list[str], tuple[int, float], int]:
    errors, totals = validate_source(repo_root)
    errors.extend(lock_blockers(repo_root))
    required_disk = 0

    if env_file is None:
        errors.append("--env-file is required for deployment mode")
        values: dict[str, str] = {}
    else:
        try:
            values = parse_env(env_file)
        except (OSError, ValueError) as exc:
            errors.append(f"cannot read deployment environment safely: {exc}")
            values = {}

    for key in THIRD_PARTY_IMAGE_KEYS:
        validate_digest_reference(key, values.get(key, ""), errors)

    release = values.get("POLARIS_RELEASE_SHA", "")
    if not RELEASE_SHA.fullmatch(release):
        errors.append("POLARIS_RELEASE_SHA must be an approved 40-hex commit")
    for key in APPLICATION_IMAGE_KEYS:
        match = APPLICATION_REFERENCE.fullmatch(values.get(key, ""))
        if not match:
            errors.append(f"{key} must use an immutable 40-hex release tag")
        elif match.group(1) != release:
            errors.append(f"{key} tag must equal POLARIS_RELEASE_SHA")

    for key in SENSITIVE_KEYS:
        value = values.get(key, "")
        upper = value.upper()
        if not value or "<" in value or "SET_ON_SERVER" in upper or "REPLACE" in upper:
            errors.append(f"{key} is missing or still a placeholder")

    total_memory, total_cpus = totals
    if host_memory_mib is None or host_memory_mib <= 0:
        errors.append("--host-memory-mib is required and must be positive")
    elif total_memory > host_memory_mib * 0.70:
        errors.append("long-running memory limits exceed 70% of host memory")
    if host_cpus is None or host_cpus <= 0:
        errors.append("--host-cpus is required and must be positive")
    elif total_cpus > host_cpus * 0.80:
        errors.append("long-running CPU limits exceed 80% of host CPUs")

    disk_inputs = (
        free_disk_mib,
        candidate_images_mib,
        paired_backup_mib,
    )
    if any(value is None or value < 0 for value in disk_inputs):
        errors.append(
            "--free-disk-mib, --candidate-images-mib and --paired-backup-mib "
            "are required and must be nonnegative"
        )
    else:
        assert free_disk_mib is not None
        assert candidate_images_mib is not None
        assert paired_backup_mib is not None
        required_disk = max(
            20 * 1024,
            2 * candidate_images_mib + paired_backup_mib + 10 * 1024,
        )
        if free_disk_mib < required_disk:
            errors.append("free Docker/backup disk is below the fail-closed reserve")

    if free_inode_percent is None or not 0 <= free_inode_percent <= 100:
        errors.append("--free-inode-percent is required in the range 0..100")
    elif free_inode_percent < 10:
        errors.append("free inode percentage is below 10%")

    return errors, totals, required_disk


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--mode", choices=("source", "deployment"), default="source")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--host-memory-mib", type=int)
    parser.add_argument("--host-cpus", type=float)
    parser.add_argument("--free-disk-mib", type=int)
    parser.add_argument("--free-inode-percent", type=float)
    parser.add_argument("--candidate-images-mib", type=int)
    parser.add_argument("--paired-backup-mib", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = (
        args.repo_root.resolve()
        if args.repo_root
        else Path(__file__).resolve().parents[1]
    )

    if args.mode == "source":
        errors, totals = validate_source(repo_root)
        errors.extend(lock_blockers(repo_root))
        if errors:
            print(f"BLOCKED source preflight ({len(errors)} issue(s))")
            for issue in errors:
                print(f"- {issue}")
            return 1
        print("PASS source preflight")
        print(
            "Long-running resource ceiling: "
            f"{totals[0]} MiB memory, {totals[1]:.2f} CPUs"
        )
        print("Requirements lock prerequisites: present")
        return 0

    errors, totals, required_disk = validate_deployment(
        repo_root=repo_root,
        env_file=args.env_file,
        host_memory_mib=args.host_memory_mib,
        host_cpus=args.host_cpus,
        free_disk_mib=args.free_disk_mib,
        free_inode_percent=args.free_inode_percent,
        candidate_images_mib=args.candidate_images_mib,
        paired_backup_mib=args.paired_backup_mib,
    )
    if errors:
        print(f"BLOCKED deployment preflight ({len(errors)} issue(s))")
        for issue in errors:
            print(f"- {issue}")
        return 1
    print("PASS deployment preflight")
    print(
        "Long-running resource ceiling: "
        f"{totals[0]} MiB memory, {totals[1]:.2f} CPUs"
    )
    print(f"Required free disk reserve: {required_disk} MiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
