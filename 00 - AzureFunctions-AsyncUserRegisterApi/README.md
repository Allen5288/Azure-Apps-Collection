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

## What I will add next in this folder

- 2026-11-21: `RegisterUser` HTTP trigger + `shared/models.py`
  (validation, Cosmos DB write, Service Bus publish).
- 2026-11-22: `ProcessRegistration` queue trigger + welcome event.
- Later: API Management in front, and a cost comparison with
  the AWS Lambda version.
