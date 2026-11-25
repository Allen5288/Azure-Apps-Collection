"""SendWelcome — Service Bus topic trigger.

Listens for the `user_registered` event published by
ProcessRegistration and sends the welcome message (email / push).
The actual sending is a small injectable function so the trigger
stays testable without an email provider: by default it logs the
welcome (stub), and a real sender can be swapped in via the
WELCOME_SENDER setting.

Idempotency: Service Bus delivers at-least-once, so a duplicate
event must not send a second welcome. The user record carries a
`welcome_sent` flag (see shared/models.py); this function checks
it first and sets it after a successful send. A duplicate delivery
finds the flag set and skips the send.

Poison handling follows ProcessRegistration: transient failures
(Cosmos DB down, sender down) raise, so the message is retried
and eventually dead-lettered by the subscription's
maxDeliveryCount. A message for a user that does not exist is a
permanent error — log it and return, so it does not retry forever.
"""

import json
import logging
import os

import azure.functions as func
from azure.cosmos import CosmosClient, exceptions as cosmos_exceptions


def _cosmos_container():
    client = CosmosClient(os.environ["COSMOS_ENDPOINT"], os.environ["COSMOS_KEY"])
    db = client.get_database_client(os.environ["COSMOS_DATABASE"])
    return db.get_container_client(os.environ["COSMOS_CONTAINER"])


def _send_welcome_stub(name: str, email: str) -> None:
    """Stub sender: logs the welcome. Swap for a real email/push sender."""
    logging.info(
        "Welcome sent to %s <%s> (stub — no email provider configured)",
        name,
        email,
    )


def send_welcome(name: str, email: str) -> None:
    """Send the welcome message. One place to swap the sender."""
    sender_name = os.environ.get("WELCOME_SENDER", "stub")
    senders = {"stub": _send_welcome_stub}
    sender = senders.get(sender_name)
    if sender is None:
        raise ValueError(f"Unknown WELCOME_SENDER: {sender_name!r}")
    sender(name, email)


def main(msg: func.ServiceBusMessage) -> None:
    """Service Bus topic trigger: one `user_registered` event per call."""
    body = json.loads(msg.get_body().decode("utf-8"))
    user_id = body.get("user_id")
    if not user_id:
        logging.error("user_registered event without user_id — dropping: %s", body)
        return

    container = _cosmos_container()
    try:
        item = container.read_item(item=user_id, partition_key=user_id)
    except cosmos_exceptions.CosmosResourceNotFoundError:
        # Permanent error: the user was never written. Retrying will
        # never help, so log it and drop the message (manual check).
        logging.error("User %s not found — dropping message, needs manual check", user_id)
        return

    if item.get("welcome_sent"):
        # Duplicate delivery (Service Bus delivers at-least-once):
        # the welcome already went out, so skip it.
        logging.info("Welcome already sent to %s — duplicate delivery, skipping", user_id)
        return

    send_welcome(item["name"], item["email"])
    item["welcome_sent"] = True
    container.replace_item(item=item["id"], body=item)
    logging.info("Welcome sent and recorded for %s", user_id)
