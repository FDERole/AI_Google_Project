# Stage 1: build the React app into static/
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npx vite build --outDir /static

# Stage 2: the FastAPI server
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY data ./data
COPY --from=web /static ./static
ENV SANJAYA_RUNTIME_DIR=/tmp/sanjaya PORT=8080
# One worker: the live chat state lives in memory.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
