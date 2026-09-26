FROM python:3.12-slim
WORKDIR /app
COPY . /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
ENV PORT=10000
EXPOSE 10000
CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT}"

VOLUME ["/app/data"]
