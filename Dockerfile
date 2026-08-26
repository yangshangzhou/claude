FROM python:3.11-slim

WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
# Use the normal Chromium build because X's web application must fully
# execute and render its client-side UI in the headless browser.
RUN playwright install --with-deps chromium

CMD uvicorn server:app --host 0.0.0.0 --port $PORT
