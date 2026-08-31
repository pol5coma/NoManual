"""Shared column helpers.

`sa_enum` keeps every enum column consistent: VARCHAR + CHECK, storing the
StrEnum *values* rather than the member names.
"""

from enum import StrEnum

from sqlalchemy import Enum


def sa_enum(python_enum: type[StrEnum], name: str) -> Enum:
    return Enum(
        python_enum,
        name=name,
        native_enum=False,
        # Without this SQLAlchemy stores member names (MANUFACTURER) instead of
        # values (manufacturer), which then leaks into the API payloads.
        values_callable=lambda enum_cls: [member.value for member in enum_cls],
        validate_strings=True,
    )
