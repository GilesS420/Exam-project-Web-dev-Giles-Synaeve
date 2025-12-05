FROM python:3.9-slim

WORKDIR /app

# Copy application code
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run the Flask app
CMD ["flask", "run", "--host=0.0.0.0", "--port=80", "--debug", "--reload"]