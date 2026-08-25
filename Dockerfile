FROM python:3.11-slim

WORKDIR /app
COPY . .
RUN pip install -r requirements.txt

CMD uvicorn server:app --host 0.0.0.0 --port $PORT
