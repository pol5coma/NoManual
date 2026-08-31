"""Domain enumerations.

All of these are stored with `native_enum=False`, which maps them to VARCHAR
plus a CHECK constraint instead of a real Postgres ENUM type. Native enums are
painful under Alembic: adding a single value needs a hand-written ALTER TYPE in
its own migration, outside the transaction.
"""

from enum import StrEnum


class TenantType(StrEnum):
    MANUFACTURER = "manufacturer"
    # Holds every manual uploaded by end users, so a public row never has to
    # pretend to be a real manufacturer.
    PUBLIC = "public"


class ProductType(StrEnum):
    WASHING_MACHINE = "washing_machine"
    DISHWASHER = "dishwasher"
    AIR_CONDITIONER = "air_conditioner"
    OVEN = "oven"
    FRIDGE = "fridge"
    TV = "tv"
    OTHER = "other"


class ManualSource(StrEnum):
    OFFICIAL = "official"
    USER_UPLOAD = "user_upload"


class ManualStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class QueryIntent(StrEnum):
    ERROR_CODE = "error_code"
    HOW_TO = "how_to"
    SAFETY = "safety"
    OUT_OF_SCOPE = "out_of_scope"


class EscalationReason(StrEnum):
    NO_ANSWER = "no_answer"
    SAFETY = "safety"
    USER_REQUEST = "user_request"


class EscalationStatus(StrEnum):
    OPEN = "open"
    SENT = "sent"
    CLOSED = "closed"
