FROM python:3.12-alpine

# Системные пакеты (tzdata для TZ)
RUN apk add --no-cache tzdata

WORKDIR /app

# Кладём метаданные проекта и исходники
COPY pyproject.toml README.md ./
COPY app ./app
COPY main.py .

# Ставим пакет и зависимости по pyproject.toml
RUN pip install --no-cache-dir .

# Директория для конфигов
RUN mkdir -p /data
ENV JARVIS_CFG=/data/config.yaml
ENV TZ=UTC

EXPOSE 8080
CMD ["python", "main.py"]
