# Built as a normal container like every other component, so build, release
# and promotion work the same way for functions.
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD exec functions-framework --target=handle --signature-type=cloudevent --port=${PORT:-8080}
