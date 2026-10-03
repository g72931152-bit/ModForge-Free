FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PORT=10000
COPY app /app/app
COPY site /app/site
RUN pip install --no-cache-dir -r /app/app/requirements.txt
VOLUME ["/app/app/data"]
EXPOSE 10000
CMD sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"
