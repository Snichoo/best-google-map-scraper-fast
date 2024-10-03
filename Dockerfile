# Use the official Playwright Docker image with Python support
FROM mcr.microsoft.com/playwright/python:v1.38.0-focal

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements.txt first to leverage Docker's caching mechanism
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code to the container
COPY . .

# Expose the port that Render.com expects applications to listen on
EXPOSE 10000

# Set environment variables if needed (optional)
# ENV API_KEY=your_api_key_here

# Command to run the FastAPI application using Uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "10000"]
