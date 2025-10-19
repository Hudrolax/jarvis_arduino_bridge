FROM python:3.12-alpine

# Системные пакеты (tzdata для TZ)
RUN apk add --no-cache tzdata

# Рабочая директория
WORKDIR /app

# Зависимости
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Код
COPY app ./app
COPY main.py .

# Директория для конфигов
RUN mkdir -p /data
ENV JARVIS_CFG=/data/config.yaml

# Таймзона из ENV (передаётся в docker-compose)
ENV TZ=UTC

# Порт для веб-интерфейса
EXPOSE 8080

CMD ["python", "main.py"]
