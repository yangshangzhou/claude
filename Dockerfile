FROM python:3.11-slim

WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
# The service runs headless only. Install only Chromium's headless shell
# to reduce the image and runtime memory footprint on Render Free.
RUN playwright install --with-deps --only-shell

CMD uvicorn server:app --host 0.0.0.0 --port $PORT
