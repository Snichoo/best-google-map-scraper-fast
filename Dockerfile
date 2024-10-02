# Use the official Playwright image with Python support
FROM mcr.microsoft.com/playwright/python:v1.39.0-focal

# Set the working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your application code
COPY . /app

# Expose the port FastAPI will run on
EXPOSE 80

# Command to run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
