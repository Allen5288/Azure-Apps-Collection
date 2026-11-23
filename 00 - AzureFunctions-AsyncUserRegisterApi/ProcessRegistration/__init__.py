"""Service Bus queue trigger: ProcessRegistration.

Consumes the message RegisterUser published, marks the user active in
Cosmos DB, and publishes a welcome event to the Service Bus topic for
the welcome sender (a later function).

Poison handling: transient failures (Cosmos DB down, Service Bus down)
raise, so the message is retried and eventually dead-lettered by the
queue's maxDeliveryCount. A message for a user that does not exist is
a permanent error — log it and return, so it does not retry forever.
Duplicate delivery is safe: a user already marked active is skipped.
"""

import json
import logging
import os

import azure.functions as func
from azure.cosmos import CosmosClient, exceptions as cosmos_exceptions
from azure.servicebus import ServiceBusClient, ServiceBusMessage


def _cosmos_container():
    client = CosmosClient(os.environ["COSMOS_ENDPOINT"], os.environ["COSMOS_KEY"])
    db = client.get_database_client(os.environ["COSMOS_DATABASE"])
    return db.get_container_client(os.environ["COSMOS_CONTAINER"])


def main(msg: func.ServiceBusMessage) -> None:
    body = json.loads(msg.get_body().decode("utf-8"))
    user_id = body["user_id"]
    logging.info("Processing registration %s", user_id)

    container = _cosmos_container()
    try:
        item = container.read_item(item=user_id, partition_key=user_id)
    except cosmos_exceptions.CosmosResourceNotFoundError:
        # Permanent error: the user was never written. Retrying will
        # never help, so log it and drop the message (manual check).
        logging.error("User %s not found — dropping message, needs manual check", user_id)
        return

    if item.get("status") == "active":
        # Duplicate delivery (Service Bus delivers at-least-once):
        # the work is already done, so skip it.
        logging.info("User %s already active — duplicate delivery, skipping", user_id)
        return

    item["status"] = "active"
    container.replace_item(item=item["id"], body=item)

    event = ServiceBusMessage(
        json.dumps({"user_id": user_id, "email": item["email"], "event": "user_registered"})
    )
    with ServiceBusClient.from_connection_string(os.environ["SERVICE_BUS_CONNECTION"]) as client:
        with client.get_topic_sender(os.environ["SERVICE_BUS_TOPIC"]) as sender:
            sender.send_messages(event)

    logging.info("User %s active; welcome event published", user_id)
