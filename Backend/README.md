# Ticket Service

## Run the ticket service

```bash
source venv/bin/activate
uvicorn ticket_service.main:app --reload
```

## Run the Billing Agent

```bash
source venv/bin/activate
uvicorn complaint_agent.main:app --host 0.0.0.0 --port 8002 --reload
```


## API Docs

Once running, open your browser at:

```
http://localhost:8000/docs
```