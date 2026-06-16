# Start with an official Python 3.10 image
FROM python:3.10-slim

# Install system dependencies needed by dlib (for face_recognition) and OpenCV
# This is the step that replaces all our manual 'sudo apt install' work
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libglib2.0-0 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file first and install dependencies
# This is cached by Docker, so it only re-runs if requirements change
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of our application code (app.py, templates, etc.) into the container
COPY . .

# Tell Docker that our app runs on port 8080
EXPOSE 8080

# The command to run when the container starts
# This will run 'python app.py'
CMD ["python", "app.py"]