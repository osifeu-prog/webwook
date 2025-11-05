FROM python:3.11-slim

# Install git and minimal deps
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV GIT_PYTHON_REFRESH=quiet

CMD ["python", "main.py"]
