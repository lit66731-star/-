FROM python:3.12-slim

WORKDIR /app

# Install deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY server.py .

# Fly.io / Render will set PORT; default 8000
ENV PORT=8000
EXPOSE 8000

CMD ["python", "server.py"]
