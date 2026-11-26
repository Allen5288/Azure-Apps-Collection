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

  ## 2026-11-27 — API Management in front of the HTTP trigger: the front door

The chain is end to end now — register → process → welcome — but
the front door is still the Functions HTTP trigger with anonymous
auth, which the 22 Nov section flagged as "local dev only". Anyone
with the URL can register users, and there is no throttling, no
key, and no public surface a client can be pointed at. Today that
changes: Azure API Management (APIM) becomes the front door, the
way API Gateway is the front door for the AWS version.

### What changes, and what does not

| | Before | After |
|---|---|---|
| Public URL | `https://<app>.azurewebsites.net/api/register` | `https://<apim>.azure-api.net/register/v1/register` |
| Who can call it | Anyone with the URL | Holders of a subscription key |
| Throttling | None — a loop can fill the queue | 100 calls/min per subscription key |
| Function auth | Anonymous (dev setting) | `function` level — APIM holds the function key, clients never see it |
| What the function code does | Unchanged | Unchanged — the policy lives in APIM, not in the function |

The function code does not change at all. That is the point: the
front door is a platform concern, and it lives in the platform.
`RegisterUser/function.json` changes one word — `authLevel` from
`anonymous` to `function` — and the key moves to APIM's named
values, where it is stored once and referenced by policy, never
pasted into code or docs.

### The policy: keys, throttling, and nothing leaking out

```xml
<!-- APIM policy on the register API (inbound section) -->
<policies>
  <inbound>
    <base />
    <!-- One subscription key per client; APIM checks it before
         the request reaches the function. No key, no call. -->
    <check-header name="Ocp-Apim-Subscription-Key" failed-check-httpcode="401"
                  failed-check-error-message="Subscription key missing or invalid" />
    <!-- 100 calls per minute per subscription. A loop filling the
         queue hits this, not the function — the same job the AWS
         usage plan will do (see the AWS notes, next section). -->
    <rate-limit-by-key calls="100" renewal-period="60"
                       counter-key="@(context.Subscription.Id)" />
    <!-- The function key is APIM's secret, not the client's.
         Strip the subscription key before forwarding, so it never
         reaches the function logs. -->
    <set-header name="Ocp-Apim-Subscription-Key" exists-action="delete" />
    <set-backend-service base-url="https://<app>.azurewebsites.net/api" />
  </inbound>
  <backend><base /></backend>
  <outbound><base /></outbound>
  <on-error><base /></on-error>
</policies>
```

Three decisions in that policy worth naming:

- **Rate limit per subscription, not per IP.** An IP is shared
  (an office NAT, a mobile carrier); a subscription is a client.
  Per-IP limiting punishes the office and lets one client behind
  many IPs through. The subscription id is the identity the rest
  of the system already uses.
- **The key is checked in APIM, not in the function.** The function
  stays small and testable; the policy is the one place keys are
  enforced. If the key check lived in the function, every new
  function would re-implement it — the same mistake as validating
  in every handler instead of at the boundary.
- **The subscription key is stripped before forwarding.** The
  function logs its requests; a key in those logs is a key in a
  log store. The function key itself is a different secret — it
  authenticates APIM to the function — and it lives in APIM's
  named values, not in the repo.

### Setting it up

```bash
# Consumption tier: no base fee, pay per call — the right start
# for a demo API. Developer (~$50/month) adds a fixed cost and
# features this API does not need yet (VNet, custom domains with
# more control); Standard adds scale and SLA. Start Consumption,
# move up when a customer contract needs the SLA.
az apim create --name <apim> --resource-group <rg> \
  --publisher-name "Harbourline" --publisher-email <email> \
  --sku-name Consumption --location australiaeast

az apim api create --service-name <apim> --resource-group <rg> \
  --api-id register-v1 --path register/v1 --display-name "Register API v1"

az apim api operation create --service-name <apim> --resource-group <rg> \
  --api-id register-v1 --operation-id post-register \
  --method POST --url-template /register

# Point the operation at the function, with the function key from
# named values — the key never appears in the command history.
az apim api update --service-name <apim> --resource-group <rg> \
  --api-id register-v1 --service-url https://<app>.azurewebsites.net/api
```

A **product** in APIM is the AWS usage plan: group the register API
into a product, hand each client a subscription to that product,
and the subscription key is their credential. Revoking a client is
revoking a subscription — no code change, no redeploy.

### JWT later, keys now

Subscription keys answer "which client is calling"; they do not
answer "which user". The Cognito / Entra ID step — APIM's
`validate-jwt` policy checking the access token, the way the API
Gateway JWT authorizer does it on AWS — comes when the API needs
per-user authorisation (only the board creator edits the board).
Keys now, JWT when the authorisation rule needs a user, not a
client. Adding JWT before there is a per-user rule would be
security theatre: a check that cannot fail is not a check.

### AWS ↔ Azure mapping, updated

| AWS (original project) | Azure (this project) |
|---|---|
| API Gateway | API Management |
| Usage plan + API key | Product + subscription |
| Throttling per key | `rate-limit-by-key` policy |
| JWT authorizer | `validate-jwt` policy (next, when per-user auth lands) |
| Stage (`prod`) | Revision (deploy a new revision, keep the old one until tested) |

### Checklist before the next deploy

- [ ] `RegisterUser` authLevel `function`; anonymous no longer
      reaches the function directly (test: the old URL without a
      key returns 401)
- [ ] APIM Consumption instance created; register API imported;
      subscription key issued for the first client
- [ ] Rate-limit policy live; tested with a burst (101 calls in a
      minute → the 101st gets 429)
- [ ] Function key in APIM named values, never in the repo or docs

### What this case still needs

- A cost comparison with the AWS Lambda version — same traffic,
  both bills, one table. That is the last piece before this case
  is finished.

### What I will add next in this folder

- A cost comparison with the AWS Lambda version.
