FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1

# Install dashboard dependencies
COPY src/dashboard/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared libraries
COPY src/agents/ /app/agents/
COPY src/simulator/ /app/simulator/
# Also copy simulator module to app root so "from exchange_data_simulator import ..." works
COPY src/simulator/exchange_data_simulator.py /app/exchange_data_simulator.py

# Copy dashboard app
COPY src/dashboard/app/ /app/app/

# Copy assets needed at runtime
COPY kql/ /app/kql/
COPY run_demo.py /app/

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
