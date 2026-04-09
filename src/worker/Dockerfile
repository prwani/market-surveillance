FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1

# Install worker dependencies
COPY src/worker/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared libraries
COPY src/agents/ /app/agents/
COPY src/simulator/ /app/simulator/

# Copy worker
COPY src/worker/worker.py /app/

EXPOSE 8080
CMD ["python", "worker.py"]
