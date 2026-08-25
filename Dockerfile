FROM python:3.11-slim

WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
RUN playwright install chromium && playwright install-deps

CMD uvicorn server:app --host 0.0.0.0 --port $PORT
