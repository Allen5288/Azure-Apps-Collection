"""Shared models for the Async User Register API.

Pure Python, no Azure imports — the domain rules live here so the
HTTP trigger (RegisterUser) and the queue trigger (ProcessRegistration)
share one definition of "a valid registration".
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
MAX_NAME_LEN = 100


@dataclass
class RegistrationRequest:
    """What the client sends to POST /api/register."""

    email: str
    name: str
    idempotency_key: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not EMAIL_RE.match(self.email or ""):
            errors.append("email must be a valid email address")
        if not self.name or len(self.name) > MAX_NAME_LEN:
            errors.append(f"name is required and at most {MAX_NAME_LEN} characters")
        if self.idempotency_key and len(self.idempotency_key) > 64:
            errors.append("idempotency_key must be at most 64 characters")
        return errors


@dataclass
class UserRecord:
    """What is stored in Cosmos DB. Partition key: /user_id."""

    user_id: str
    email: str
    name: str
    status: str = "pending"  # pending -> active
    idempotency_key: str = ""
    created_at: str = ""

    def to_cosmos_item(self) -> dict:
        item = asdict(self)
        item["id"] = self.user_id  # Cosmos DB requires an `id`
        return item


def new_user_id() -> str:
    return str(uuid.uuid4())


def registration_id_for(idempotency_key: str) -> str:
    """Deterministic id from the client's idempotency key.

    A retried request with the same key maps to the same user id, so
    the Cosmos DB write is naturally idempotent — the second attempt
    finds the existing record instead of creating a duplicate.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"registration:{idempotency_key}"))
