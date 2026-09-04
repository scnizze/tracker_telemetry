# Start from an official, minimal Python image (Debian-based, no extra bloat)
FROM python:3.12-slim

# Everything from here on happens inside this directory in the image
WORKDIR /app

# Copy ONLY the dependency list first, not the whole app yet
COPY requirements.txt .

# Install dependencies into the image
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the actual application code
COPY app/ ./app/

# Documentation only -- tells humans/tools which port the app uses
EXPOSE 8000

# The command that runs when a container starts from this image
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
