FROM python:3.10-slim
WORKDIR /app
RUN pip install aiohttp redis
COPY main.py .
CMD ["python", "main.py"]
