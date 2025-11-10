FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    git \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV GIT_PYTHON_REFRESH=quiet
ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
