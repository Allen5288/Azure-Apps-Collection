# Azure Deployment Project Collections

A collection of Azure serverless applications and deployment patterns, built with Azure Functions and other Azure services. Each project is a working example of a real deployment pattern — not just a code snippet — with its own detailed README explaining the architecture, setup, and trade-offs.

## 🎯 Overview

This repository contains hands-on Azure deployment examples, starting with an asynchronous user-registration API built on Azure Functions. The first project is an Azure mirror of the AWS Async User Register API (00 - AsyncUserRegisterApi in [AWS-Apps-Collection](https://github.com/Allen5288/AWS-Apps-Collection)): the same event-driven pattern, rebuilt with Azure services, so the two collections can be compared side by side.

The project is a daily build, started 2026-11-20, and the folder will be extended over the next few days. Each project folder contains its own detailed README with setup instructions, architecture, and next steps.

## 📂 Projects

### 00 - AzureFunctions-AsyncUserRegisterApi

**Technology Stack:** Python, Azure Functions, Cosmos DB (NoSQL API), Service Bus topic and queue, API Management / Functions HTTP

**Architecture:** Event-driven serverless application with asynchronous processing

An async user-registration API. The client gets an immediate 202 Accepted response with a registration id, while the real work — validation, storing the user, and sending a welcome message — happens asynchronously.

1. The client sends `POST /api/register` to an Azure Functions HTTP trigger (Python).
2. The function validates the input, writes the user record to Cosmos DB, and publishes a registration event to a Service Bus topic.
3. A Service Bus-triggered function reads the message, marks the user active in Cosmos DB, and publishes a welcome event.
4. A welcome function sends the welcome message (email / push — stubbed for now).

**Key Features:**
- Immediate 202 Accepted response with a registration id, so the client never waits on slow work
- Input validation before the user record is stored
- User records stored in Cosmos DB (NoSQL API), partitioned by `user_id`
- Pub/sub welcome flow via a Service Bus topic and queue
- Consumption plan — pay per execution, so an idle app costs almost nothing

**Azure Services Used:**
- Azure Functions (HTTP trigger and Service Bus trigger)
- Cosmos DB (NoSQL API)
- Service Bus topic
- Service Bus queue
- API Management / Functions HTTP

**AWS → Azure mapping:**
| AWS (AWS-Apps-Collection) | Azure (this repo) |
| --- | --- |
| Lambda | Azure Functions |
| DynamoDB | Cosmos DB (NoSQL API), partition by `user_id` |
| SNS | Service Bus topic |
| SQS | Service Bus queue |
| API Gateway | API Management / Functions HTTP |

**Status:** The design and documentation are in place; the function code lands next — the RegisterUser HTTP trigger and `shared/models.py` on 2026-11-21, then the ProcessRegistration queue trigger and welcome event on 2026-11-22.

[📖 View Project Details](./00%20-%20AzureFunctions-AsyncUserRegisterApi/README.md)

## 🚀 Getting Started

Each project contains its own detailed README with specific setup instructions. Generally, you'll need:

### Prerequisites
- An Azure account with appropriate permissions
- Azure CLI installed and configured
- Azure Functions Core Tools (`func`) and Python 3.12

### General Setup Steps
1. Sign in to Azure:
   ```bash
   az login
   ```
2. Create the function app (consumption plan, `australiaeast`, Python 3.12, Functions v4):
   ```bash
   az functionapp create --consumption-plan-location australiaeast --runtime python --runtime-version 3.12 --functions-version 4 --name <your-app> --storage <your-storage>
   ```
3. Run the function app locally:
   ```bash
   func start
   ```
4. Test the registration endpoint:
   ```bash
   curl -X POST http://localhost:7071/api/register -H "Content-Type: application/json" -d '{"email":"a@example.com","name":"Allen"}'
   ```

> Note: these run steps apply once the function code lands in the project folder — see the project's [README](./00%20-%20AzureFunctions-AsyncUserRegisterApi/README.md) for its schedule.

### Cost and cleanup
- The consumption plan is pay-per-execution, so an idle app costs almost nothing; Cosmos DB has a serverless / free tier option.
- Delete the resource group when finished:
  ```bash
  az group delete --name <rg> --yes
  ```
- Never commit `local.settings.json` — it holds secrets.

## 🛠️ Azure Services Covered

| Service | Purpose | Projects |
| --- | --- | --- |
| Azure Functions | Serverless compute (HTTP and Service Bus triggers) | 00 - Async User Register API |
| Cosmos DB (NoSQL API) | NoSQL database for user records | 00 - Async User Register API |
| Service Bus topic | Pub/sub messaging for registration events | 00 - Async User Register API |
| Service Bus queue | Message queueing for background processing | 00 - Async User Register API |
| API Management / Functions HTTP | HTTP API front door | 00 - Async User Register API |

## 🎓 Learning Outcomes

Through these projects, you will learn:
- **Serverless Architecture Patterns**: Event-driven design, asynchronous processing, and message-based decoupling
- **Azure Service Integration**: How Azure Functions, Cosmos DB, and Service Bus work together in a real application
- **Deployment Automation**: Azure CLI, the consumption plan, and managing resources from the command line
- **API Design**: Async request patterns — return 202 Accepted immediately, do the slow work in the background
- **Cloud Cost Management**: Consumption pricing, Cosmos DB serverless / free tier, and cleaning up resources when finished

## 📈 Future Projects

- API Management in front of the register API, and a cost comparison with the AWS Lambda version
- More Azure deployment examples and patterns to follow — this collection grows alongside the AWS collection

## 🤝 Contributing

Contributions and suggestions are welcome! If you'd like to add a project or improve the documentation:
- Fork this repository
- Create a feature branch for your changes
- Submit a pull request with a clear description of the improvements

## 📄 License

This project collection is provided for educational and demonstration purposes.
