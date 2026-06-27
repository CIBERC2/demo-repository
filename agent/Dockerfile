FROM python:3.12-slim

WORKDIR /app

# Copiar módulos compartidos del servidor
COPY ../server/core /app/server/core
COPY ../server/__init__.py /app/server/__init__.py 2>/dev/null || true

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV C2_SERVER=ws://localhost:8000/ws

CMD ["python", "agent.py", "--server", "${C2_SERVER}"]
