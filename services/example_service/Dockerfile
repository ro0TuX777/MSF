FROM python:3.11-slim
WORKDIR /app
COPY services/example_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/example_service/app.py .
EXPOSE 8610
CMD ["python", "app.py"]
