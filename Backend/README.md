# Backend

Copy `.env.example` to `.env` and configure Google Cloud / Vertex AI credentials before running.

```bash
pip install -r requirements.txt
```

Required `.env` values:
- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_CLOUD_LOCATION`
- `GOOGLE_APPLICATION_CREDENTIALS`
- `GEMINI_MODEL`

Run each service in a separate terminal from the `Backend` directory.

## Ticket service

```bash
source venv/bin/activate
set -a && source .env && set +a
uvicorn ticket_service.main:app --reload --port $TICKET_SERVICE_PORT
```

## Intent detector (orchestrator)

```bash
source venv/bin/activate
set -a && source .env && set +a
uvicorn intent_detector_agent.main:app --port $INTENT_DETECTOR_PORT
```

## Billing agent

```bash
source venv/bin/activate
set -a && source .env && set +a
uvicorn billing_agent.main:app --port $BILLING_AGENT_PORT
```

## Complaint agent

```bash
source venv/bin/activate
set -a && source .env && set +a
uvicorn complaint_agent.main:app --port $COMPLAINT_AGENT_PORT
```

## Sales agent

```bash
source venv/bin/activate
set -a && source .env && set +a
uvicorn sales_agent.main:app --port $SALES_AGENT_PORT
```

## API docs

- Ticket service: http://localhost:8000/docs
- Intent detector: http://localhost:8001/docs

Ports are configured in `.env`.
