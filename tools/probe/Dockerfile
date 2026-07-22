FROM python:3.12-slim
RUN pip install --no-cache-dir google-cloud-storage
WORKDIR /app
COPY probe_lib.py main.py /app/
CMD ["python", "main.py"]
