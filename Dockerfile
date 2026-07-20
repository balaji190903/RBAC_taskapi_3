# Step 1: Use an official lightweight Python image
FROM python:3.12-slim

# Step 2: Set the working directory inside the container
WORKDIR /app

# Step 3: Copy the requirements file and install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Step 4: Copy the application code and supporting scripts
COPY app/ app/
COPY scripts/ scripts/

# Step 5: Inform Docker that the container listens on port 8000
EXPOSE 8000

# Step 6: Start FastAPI server with uvicorn listening on 0.0.0.0:8000
CMD ["python", "scripts/run_server.py"]
