FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY static ./static
COPY data ./data
ENV SANJAYA_RUNTIME_DIR=/tmp/sanjaya PORT=8080
# One worker: the live chat state lives in memory.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
