# One image per product. Workloads choose what to run via command/args in deploy/main.tf.
FROM python:3.13-slim
WORKDIR /app
COPY src/ .
ENTRYPOINT ["python", "main.py"]
