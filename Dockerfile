FROM python:3.12-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir fastapi uvicorn python-multipart
ENV PORT=10000
EXPOSE 10000
CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT}"

VOLUME ["/app/data"]
