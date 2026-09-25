FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY main.py /app/main.py
COPY site_config.json /app/site_config.json
COPY assets /app/assets
RUN pip install --no-cache-dir fastapi uvicorn python-multipart
ENV PORT=10000
EXPOSE 10000
CMD ["sh","-c","uvicorn main:app --host 0.0.0.0 --port $PORT"]
