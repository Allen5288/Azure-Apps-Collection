# 00 - Async User Register API — Azure Functions version

> Daily build, started 2026-11-20. This is the Azure mirror of
> `AWS-Apps-Collection / 00 - AsyncUserRegisterApi`.
> Same pattern, Azure services. This folder will be extended over
> the next few days — one build, one folder.

## What this is

An asynchronous user-registration API. The client gets an immediate
`202 Accepted` with a registration id, and the real work — validation,
storing the user, sending a welcome message — happens in the
background, so a slow downstream service never blocks the signup.

## Architecture

```text
Client
  │  POST /api/register
  ▼
Azure Functions (HTTP trigger, Python)
  │  1. Validate input, write user record (status: pending)
  │  2. Publish message to Service Bus queue
  ▼
Azure Functions (Service Bus trigger)
  │  1. Read message, mark user active in Cosmos DB
  │  2. Publish welcome event
  ▼
Azure Functions (Service Bus trigger, welcome)
  └─► Send welcome message (email / push — stubbed for now)
```

## AWS → Azure mapping

| AWS (original project) | Azure (this project) | Why |
|---|---|---|
| Lambda | Azure Functions | Serverless compute, HTTP + queue triggers |
| DynamoDB | Cosmos DB (NoSQL API) | Document store, partition by `user_id` |
| SNS | Service Bus topic | Pub/sub for the welcome event |
| SQS | Service Bus queue | Reliable queue for registration work |
| API Gateway | API Management / Functions HTTP | HTTP entry point, throttling, keys |

## Project structure (planned)

```text
00 - AzureFunctions-AsyncUserRegisterApi/
├── README.md            # this file
├── host.json
├── local.settings.json.example   # copy to local.settings.json, never commit secrets
├── requirements.txt
├── RegisterUser/        # HTTP trigger
│   ├── __init__.py
│   └── function.json
├── ProcessRegistration/ # Service Bus queue trigger
│   ├── __init__.py
│   └── function.json
└── shared/
    └── models.py        # User record, validation
```

## Local run (next day, once the code lands)

```bash
az login
az functionapp create --consumption-plan-location australiaeast \
  --runtime python --runtime-version 3.12 \
  --functions-version 4 --name <your-app> --storage <your-storage>
func start
curl -X POST http://localhost:7071/api/register \
  -H "Content-Type: application/json" \
  -d '{"email":"a@example.com","name":"Allen"}'
```

## Cost and cleanup

- Consumption plan: you pay per execution, not per server.
  Idle costs ~$0 — good for a learning project.
- Cosmos DB serverless / free tier for dev; delete the resource
  group when done: `az group delete --name <rg> --yes`
- Never commit `local.settings.json` — connection strings live
  there. Use the `.example` file as the template.

## 2026-11-22 — `RegisterUser` HTTP trigger landed

The trigger planned for 21 Nov is now real code in this folder
(Azure was not the cloud pick on 21 Nov, so it lands a day late):

- `shared/models.py` — pure-Python domain models: `RegistrationRequest`
  validation (email format, name length, idempotency key) and
  `UserRecord` for Cosmos DB. No Azure imports here, so the queue
  trigger reuses the same rules.
- `shared/__init__.py` — makes `shared` an importable package.
- `RegisterUser/__init__.py` — the HTTP trigger: validate, write a
  `pending` user record to Cosmos DB, publish to the Service Bus
  queue, return `202 Accepted` with the registration id.
- `RegisterUser/function.json` — HTTP trigger binding, `POST
  /api/register`, anonymous auth for local dev (use `function` level
  or API Management keys before exposing this publicly).

### Idempotency, by construction

A client may retry a request (timeout, flaky network) and must never
create two users. The client sends an `idempotency_key`; the user id
is derived deterministically from it (`uuid5`), so a retried request
hits the same Cosmos DB `id` and the second write returns
`CosmosResourceExistsError` — caught, logged, and answered with the
same `202`. No separate idempotency table, no race: the Cosmos DB
`id` uniqueness is the guard.

### What I will add next in this folder

- Next: the welcome sender function (Service Bus topic trigger) + API Management in front.
- Later: API Management in front, and a cost comparison with
  the AWS Lambda version.

## 2026-11-24 — `ProcessRegistration` queue trigger landed

The second half of the chain is now real code: `RegisterUser` publishes to the queue, `ProcessRegistration` does the slow work.

- `ProcessRegistration/__init__.py` — Service Bus queue trigger: read the message, fetch the user from Cosmos DB, mark it `active`, publish a `user_registered` welcome event to the Service Bus topic. It reuses `shared/models.py` — no duplicated validation or record shape.
- `ProcessRegistration/function.json` — `serviceBusTrigger` on `%SERVICE_BUS_QUEUE%`, connection from the `SERVICE_BUS_CONNECTION` app setting.
- New environment variable: `SERVICE_BUS_TOPIC` (the topic the welcome event goes to; the queue trigger only needs the queue name).

### Idempotency, again — at-least-once delivery

Service Bus delivers at-least-once, so this function must be safe to run twice for the same message. It is, by the status check: a user already `active` is skipped, so a duplicate delivery changes nothing. The Cosmos DB `replace_item` is the same write either way.

### Poison handling — retry transient, drop permanent

- Transient failure (Cosmos DB or Service Bus down): the exception propagates, the message is retried, and after `maxDeliveryCount` (set 5 on the queue) it is dead-lettered automatically. Nothing is lost silently.
- Permanent failure (user id not in Cosmos DB): logged as an error and dropped. Retrying a message that can never succeed would poison the queue; this one needs a human to look at why the record is missing.
- The AWS mirror has the same shape: SQS redrive to a DLQ after `maxReceiveCount` 3. Azure just makes the DLQ automatic per queue.

## 2026-11-26 — `SendWelcome` topic trigger landed

The last link in the chain is now real code: `ProcessRegistration`
publishes `user_registered` to the topic, `SendWelcome` subscribes
and sends the welcome message. The trigger, the subscription, and
the idempotency are now real code — only the sending itself is
still a stub (the log line), and swapping in a real email provider
is a config change. The architecture diagram's "stubbed for now"
now refers to the sender only, not to this step of the chain.

- `SendWelcome/__init__.py` — Service Bus topic trigger: parse the
  event, fetch the user from Cosmos DB, skip if `welcome_sent` is
  already set, send the welcome, then set the flag. The sender is
  one injectable function (`send_welcome`, `WELCOME_SENDER` env),
  so swapping the log stub for a real email provider (SendGrid,
  Azure Communication Services) is a config change, not a rewrite.
  - `SendWelcome/function.json` — `serviceBusTrigger` on
    `%SERVICE_BUS_TOPIC%` / `%SERVICE_BUS_WELCOME_SUBSCRIPTION%`,
    connection from the `SERVICE_BUS_CONNECTION` app setting.
  - `shared/models.py` — `welcome_sent: bool = False` added to
    `UserRecord`, so new records carry the flag from the start
    (`to_cosmos_item` includes it automatically).
  - New environment variable: `SERVICE_BUS_WELCOME_SUBSCRIPTION`
    (the subscription name on the welcome topic) and `WELCOME_SENDER`
    (`stub` by default).

  ### Idempotency, a third time — the flag pattern

  The two earlier functions used different guards for the same
  problem: `RegisterUser` derives the user id from the idempotency
  key (the Cosmos DB `id` is the guard), `ProcessRegistration`
  checks the `active` status. `SendWelcome` uses a third shape, a
  `welcome_sent` flag on the user record, because the guard here is
  about an action, not a record: sending a welcome twice is the
  failure, and the flag is the record that it happened. Three
  functions, three guards, one rule — **a duplicate delivery must
  change nothing**. The flag is written with `replace_item` right
  after the send; a crash between send and flag-write can still
  double-send, and that is accepted: a duplicate welcome email is
  embarrassing, a lost welcome is a broken signup. When the cost of
  a duplicate is higher than the cost of a loss, the order reverses
  — flag first, then send — and that trade-off belongs in the code
  comment, not in a post-incident review.

  ### Poison handling — same rule as ProcessRegistration

  - Transient failure (Cosmos DB or the sender down): the exception
    propagates, the message is retried, and after `maxDeliveryCount`
    on the subscription it is dead-lettered automatically.
  - Permanent failure (user id not in Cosmos DB, event without a
    `user_id`): logged as an error and dropped. Retrying a message
    that can never succeed would poison the subscription.
  - Unknown `WELCOME_SENDER`: raises `ValueError` on purpose — a
    misconfigured sender should fail loudly at startup, not silently
    swallow welcomes.

  ### What this case still needs

  The Azure mirror of the AWS API is now end to end: register →
  process → welcome. What is left is the front door and the bill:

  - API Management in front of the HTTP trigger (keys, throttling,
    the public surface the AWS version gets from API Gateway).
  - A cost comparison with the AWS Lambda version — same traffic,
    both bills, one table.

  ### What I will add next in this folder

  - API Management in front of the HTTP trigger.
  - A cost comparison with the AWS Lambda version.
  
  
