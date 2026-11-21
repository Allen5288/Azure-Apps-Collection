"""HTTP trigger: POST /api/register.

Accepts a registration, validates it, stores a `pending` user record
in Cosmos DB, and publishes a message to the Service Bus queue for
the ProcessRegistration function. Returns 202 Accepted immediately —
the slow work happens in the background.

Environment variables (local.settings.json locally, app settings in
Azure — never commit the real values):
  COSMOS_ENDPOINT, COSMOS_KEY, COSMOS_DATABASE, COSMOS_CONTAINER,
  SERVICE_BUS_CONNECTION, SERVICE_BUS_QUEUE
"""

import json
import logging
import os
from datetime import datetime, timezone

import azure.functions as func
from azure.cosmos import CosmosClient, exceptions as cosmos_exceptions
from azure.servicebus import ServiceBusClient, ServiceBusMessage

from shared.models import (
    RegistrationRequest,
    UserRecord,
    new_user_id,
    registration_id_for,
)


def _cosmos_container():
    client = CosmosClient(os.environ["COSMOS_ENDPOINT"], os.environ["COSMOS_KEY"])
    db = client.get_database_client(os.environ["COSMOS_DATABASE"])
    return db.get_container_client(os.environ["COSMOS_CONTAINER"])


def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse("Request body must be valid JSON.", status_code=400)

    registration = RegistrationRequest(
        email=str(body.get("email", "")),
        name=str(body.get("name", "")),
        idempotency_key=str(body.get("idempotency_key", "")),
    )
    errors = registration.validate()
    if errors:
        return func.HttpResponse(json.dumps({"errors": errors}), status_code=400, mimetype="application/json")

    user_id = (
        registration_id_for(registration.idempotency_key)
        if registration.idempotency_key
        else new_user_id()
    )
    record = UserRecord(
        user_id=user_id,
        email=registration.email,
        name=registration.name,
        idempotency_key=registration.idempotency_key,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    container = _cosmos_container()
    try:
        container.create_item(record.to_cosmos_item())
    except cosmos_exceptions.CosmosResourceExistsError:
        # Same idempotency key retried: the record already exists.
        # Return the same 202 instead of creating a duplicate user.
        logging.info("Duplicate registration for key %s — returning existing id", registration.idempotency_key)
    except cosmos_exceptions.CosmosHttpResponseError:
        logging.exception("Cosmos DB write failed")
        return func.HttpResponse("Registration could not be saved.", status_code=500)

    message = ServiceBusMessage(json.dumps({"user_id": user_id, "email": record.email}))
    with ServiceBusClient.from_connection_string(os.environ["SERVICE_BUS_CONNECTION"]) as client:
        with client.get_queue_sender(os.environ["SERVICE_BUS_QUEUE"]) as sender:
            sender.send_messages(message)

    return func.HttpResponse(
        json.dumps({"registration_id": user_id, "status": "pending"}),
        status_code=202,
        mimetype="application/json",
    )
