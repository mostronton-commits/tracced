FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY tracced/ ./tracced/
COPY config.yaml .
# Keys come from the environment (.env), never from the image.
CMD ["python", "-m", "tracced.web"]
