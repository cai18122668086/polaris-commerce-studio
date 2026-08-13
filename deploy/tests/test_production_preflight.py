from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEPLOY))

from generate_production_env import (
    IMAGE_KEYS,
    PROVIDER_KEYS,
    SUPERTOKENS_IMAGE,
)
from production_preflight import (
    validate_backend_dockerfile,
    validate_caddy,
    validate_compose,
    validate_env,
)


class ProductionPreflightTests(unittest.TestCase):
    def valid_env(self) -> dict[str, str]:
        sha = "b" * 40
        digest = "a" * 64
        env = {
            "POLARIS_RELEASE_SHA": sha,
            "POLARIS_BACKEND_IMAGE": f"polaris/backend:{sha}",
            "POLARIS_FRONTEND_IMAGE": f"polaris/frontend:{sha}",
            "POLARIS_SUPERTOKENS_IMAGE": SUPERTOKENS_IMAGE,
            "POLARIS_POSTGRES_PASSWORD": "p" * 32,
            "POLARIS_REDIS_PASSWORD": "r" * 32,
            "POLARIS_MINIO_ROOT_USER": "minio-production-user",
            "POLARIS_MINIO_ROOT_PASSWORD": "m" * 32,
            "POLARIS_ACCESS_URL_SECRET": "a" * 48,
            "POLARIS_SUPERTOKENS_API_KEY": "s" * 64,
            "POLARIS_AUTH_SMTP_HOST": "smtp.example.com",
            "POLARIS_AUTH_SMTP_PORT": "587",
            "POLARIS_AUTH_SMTP_USERNAME": "smtp-user",
            "POLARIS_AUTH_SMTP_PASSWORD": "smtp-password",
            "POLARIS_AUTH_SMTP_SECURE": "false",
            "POLARIS_AUTH_EMAIL_FROM_NAME": "Polaris Commerce Studio",
            "POLARIS_AUTH_EMAIL_FROM_ADDRESS": "no-reply@mail.tengliapi.xyz",
            "POLARIS_ACME_EMAIL": "ops@tengliapi.xyz",
            "POLARIS_S3_BUCKET": "polaris-production",
        }
        env.update({key: f"example/{key.lower()}:approved@sha256:{digest}" for key in IMAGE_KEYS})
        defaults = {
            "POLARIS_TASK_RUNNER": "mock",
            "POLARIS_PROVIDER_QUOTA_ENABLED": "true",
            "POLARIS_WORKSPACE_CREDIT_ENFORCEMENT_ENABLED": "false",
            "POLARIS_PRODUCT_IMAGE_PROVIDER_ENABLED": "false",
            "POLARIS_REFERENCE_REMIX_PROVIDER_ENABLED": "false",
            "POLARIS_MODEL_POSE_TRANSFER_PROVIDER_ENABLED": "false",
            "POLARIS_CREATIVE_IMAGE_PROVIDER_ENABLED": "false",
            "POLARIS_AMAZON_VISUAL_SUITE_PROVIDER_ENABLED": "false",
            "POLARIS_CROSSBORDER_DETAIL_PROVIDER_ENABLED": "false",
            "POLARIS_TENGLI_API_KEY": "",
            "POLARIS_TENGLI_BASE_URL": "https://api.tengliapi.xyz:8443",
            "POLARIS_TENGLI_IMAGE_MODEL": "gpt-image-2",
            "POLARIS_TENGLI_VISION_MODEL": "gpt-5.6-terra",
            "POLARIS_TENGLI_SMOKE_BUDGET_USD": "200",
            "POLARIS_TENGLI_DAILY_BUDGET_USD": "0",
            "POLARIS_TENGLI_MONTHLY_BUDGET_USD": "0",
            "POLARIS_TENGLI_DAILY_REQUEST_LIMIT": "0",
            "POLARIS_TENGLI_PLANNER_RESERVE_MICROS": "250000",
            "POLARIS_XINGHE_CONCURRENCY": "2",
            "POLARIS_XINGHE_SKILL_ROOT": "/app/skill_sources/xinghe-ecommerce-detail",
        }
        env.update(defaults)
        return env

    def test_repository_production_files_pass_static_checks(self) -> None:
        compose = (DEPLOY / "compose.production.yml").read_text(encoding="utf-8")
        caddy = (DEPLOY / "Caddyfile.production").read_text(encoding="utf-8")
        dockerfile = (DEPLOY / "backend.Dockerfile").read_text(encoding="utf-8")
        self.assertEqual(validate_compose(compose), [])
        self.assertEqual(validate_caddy(caddy), [])
        self.assertEqual(validate_backend_dockerfile(dockerfile), [])
        self.assertEqual(validate_env(self.valid_env()), [])

    def test_env_generator_tracks_every_compose_provider_flag(self) -> None:
        compose = (DEPLOY / "compose.production.yml").read_text(encoding="utf-8")
        compose_provider_keys = set(
            re.findall(r"\$\{(POLARIS_[A-Z0-9_]+_PROVIDER_ENABLED)(?=[:}])", compose)
        )
        generated_provider_keys = {
            key for key in PROVIDER_KEYS if key.endswith("_PROVIDER_ENABLED")
        }
        self.assertEqual(generated_provider_keys, compose_provider_keys)

    def test_shared_data_volume_drift_is_rejected(self) -> None:
        compose = (DEPLOY / "compose.production.yml").read_text(encoding="utf-8")
        mutations = (
            compose.replace(
                "polaris-internal-staging_redis_data",
                "polaris-production_redis_data",
            ),
            compose.replace(
                "polaris-internal-staging_minio_data",
                "polaris-production_minio_data",
            ),
            compose.replace(
                "  redis_data:\n    name: polaris-internal-staging_redis_data\n    external: true",
                "  redis_data:\n    name: polaris-internal-staging_redis_data",
            ),
            compose.replace("- minio_data:/data", "- minio_data:/srv/minio"),
        )
        for mutated in mutations:
            with self.subTest():
                self.assertTrue(validate_compose(mutated))

    def test_owner_script_packaging_is_required_and_narrow(self) -> None:
        owner_copy = (
            "COPY backend/scripts/assign_workspace_owner.py "
            "./scripts/assign_workspace_owner.py\n"
        )
        self.assertTrue(validate_backend_dockerfile("FROM scratch\n"))
        forbidden_copies = (
            "COPY backend/scripts ./scripts\n",
            "COPY backend/scripts/ ./scripts/\n",
            "ADD backend/scripts ./scripts\n",
            'COPY ["backend/scripts", "./scripts"]\n',
            "COPY backend/scripts/export_openapi.py ./scripts/export_openapi.py\n",
        )
        for forbidden in forbidden_copies:
            with self.subTest(forbidden=forbidden):
                self.assertTrue(validate_backend_dockerfile(forbidden + owner_copy))

    def test_supertokens_api_key_rejects_underscore(self) -> None:
        env = self.valid_env()
        env["POLARIS_SUPERTOKENS_API_KEY"] = "a" * 40 + "_"
        errors = validate_env(env)
        self.assertTrue(any("characters rejected" in error for error in errors))

    def test_template_markers_and_short_secrets_fail(self) -> None:
        env = self.valid_env()
        env["POLARIS_SUPERTOKENS_API_KEY"] = "<GENERATE_ON_SERVER>"
        errors = validate_env(env)
        self.assertTrue(any("POLARIS_SUPERTOKENS_API_KEY" in error for error in errors))

    def test_provider_drift_is_detected_without_values(self) -> None:
        env = self.valid_env()
        base = {key: env[key] for key in PROVIDER_KEYS}
        env["POLARIS_TASK_RUNNER"] = "tengli"
        errors = validate_env(env, base)
        self.assertIn("Provider settings changed during auth cutover: POLARIS_TASK_RUNNER", errors)


if __name__ == "__main__":
    unittest.main()
