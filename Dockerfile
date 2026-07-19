FROM python:latest
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install fastapi[standard]
RUN pip install itsdangerous
COPY . ./ 
ENTRYPOINT ["uvicorn", "backend.app:app", "--host", "0.0.0.0","--port", "8000"]


