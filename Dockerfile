# Pega um sistema Linux levinho já com Python 3.10
FROM python:3.10-slim

# Instala o FFmpeg (para o yt-dlp não dar aquele erro 500)
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

# Diz para o servidor trabalhar dentro da pasta /app
WORKDIR /app

# Copia o arquivo de dependências e instala tudo
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o resto do seu código (download.py, etc) pra dentro do servidor
COPY . .

# Comando que o Render vai rodar para ligar a API
# (O Render gosta de usar a porta 10000 por padrão em vez de 8000)
CMD ["uvicorn", "download:app", "--host", "0.0.0.0", "--port", "10000"]