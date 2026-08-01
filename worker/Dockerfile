# Pakai image resmi Playwright yang udah include Chromium dependencies
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy
WORKDIR /app
RUN pip install redis playwright
RUN playwright install chromium
COPY main.py .
CMD ["python", "main.py"]
