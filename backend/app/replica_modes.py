"""Versioned public modes, separate from the Skill bound to historical plans."""

from collections.abc import Mapping
from typing import Any

MODE_VERSION = "replica-modes-v2"


def execution_method(values: Mapping[str, Any]) -> str:
    method = values["replication_method"]
    if values.get("replica_mode_version") == MODE_VERSION and method == "style":
        # Style imitation now uses the former fast exact-composition workflow.
        return "exact"
    return method
