from enum import StrEnum


class UserStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class WorkspaceStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class MembershipRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    INVITED = "invited"
    SUSPENDED = "suspended"


class AssetMediaKind(StrEnum):
    IMAGE = "image"
    MASK = "mask"
    JSON = "json"
    ARCHIVE = "archive"


class AssetOriginKind(StrEnum):
    UPLOAD = "upload"
    GENERATED = "generated"
    IMPORTED = "imported"
    DERIVED = "derived"


class AssetLifecycleStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    QUARANTINED = "quarantined"
    FAILED = "failed"
    DELETED = "deleted"


class JobType(StrEnum):
    LOCAL_EDIT = "local_edit"
    PRODUCT_IMAGE = "product_image"
    REFERENCE_REMIX = "reference_remix"
    CREATIVE_IMAGE = "creative_image"
    DETAIL_PACK = "detail_pack"
    AMAZON_VISUAL_SUITE = "amazon_visual_suite"


class JobStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    PLANNING = "planning"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    PROCESSING = "processing"
    CANCELLING = "cancelling"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_JOB_STATUSES = {
    JobStatus.PARTIAL,
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}

JOB_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.DRAFT: {JobStatus.QUEUED, JobStatus.CANCELLED},
    JobStatus.QUEUED: {
        JobStatus.PLANNING,
        JobStatus.PROCESSING,
        JobStatus.CANCELLING,
        JobStatus.CANCELLED,
        JobStatus.FAILED,
    },
    JobStatus.PLANNING: {
        JobStatus.AWAITING_CONFIRMATION,
        JobStatus.PROCESSING,
        JobStatus.CANCELLING,
        JobStatus.FAILED,
    },
    JobStatus.AWAITING_CONFIRMATION: {
        JobStatus.PROCESSING,
        JobStatus.CANCELLING,
        JobStatus.CANCELLED,
        JobStatus.FAILED,
    },
    JobStatus.PROCESSING: {
        JobStatus.CANCELLING,
        JobStatus.PARTIAL,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
    },
    JobStatus.CANCELLING: {JobStatus.CANCELLED},
}


class JobItemStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    REUSED = "reused"


class AttemptStatus(StrEnum):
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"
    CANCELLED = "cancelled"


class PlanValidationStatus(StrEnum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"


class UsageCompleteness(StrEnum):
    NONE = "none"
    PARTIAL = "partial"
    COMPLETE = "complete"


class IdempotencyStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class CreditReservationStatus(StrEnum):
    ACTIVE = "active"
    SETTLED = "settled"
    RELEASED = "released"


class RetryScope(StrEnum):
    FULL = "full"
    FAILED = "failed"
    MISSING = "missing"
    SELECTED = "selected"


class JobAssetDirection(StrEnum):
    INPUT = "input"
    INTERMEDIATE = "intermediate"
    OUTPUT = "output"


def can_transition(current: JobStatus, target: JobStatus) -> bool:
    return target in JOB_TRANSITIONS.get(current, set())
