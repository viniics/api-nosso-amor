FROM python:3.10-slim

RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
#f
CMD ["uvicorn", "download:app", "--host", "0.0.0.0", "--port", "10000"]
