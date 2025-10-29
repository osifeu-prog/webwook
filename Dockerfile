FROM python:3.11-slim

# Install Git and other dependencies
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set environment variable for Git Python
ENV GIT_PYTHON_REFRESH=quiet

# Run the application
CMD ["python", "main.py"]
