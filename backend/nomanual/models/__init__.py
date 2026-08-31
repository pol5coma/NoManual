"""SQLAlchemy models.

Importing every model here gives Alembic a single import that populates
Base.metadata with the full schema.
"""

from nomanual.models.api_key import ApiKey
from nomanual.models.base import Base
from nomanual.models.chunk import Chunk
from nomanual.models.client import Client
from nomanual.models.enums import (
    EscalationReason,
    EscalationStatus,
    ManualSource,
    ManualStatus,
    ProductType,
    QueryIntent,
    TenantType,
)
from nomanual.models.escalation import Escalation
from nomanual.models.indexed_page import IndexedPage
from nomanual.models.manual import Manual, manual_product
from nomanual.models.product import Product
from nomanual.models.query_log import QueryLog
from nomanual.models.tenant import Tenant

__all__ = [
    "ApiKey",
    "Base",
    "Chunk",
    "Client",
    "Escalation",
    "EscalationReason",
    "EscalationStatus",
    "IndexedPage",
    "Manual",
    "ManualSource",
    "ManualStatus",
    "Product",
    "ProductType",
    "QueryIntent",
    "QueryLog",
    "Tenant",
    "TenantType",
    "manual_product",
]
