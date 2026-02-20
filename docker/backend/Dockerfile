FROM python:3.12-slim

# Sistema + LibreOffice para conversión DOCX→PDF + Fuentes Microsoft
RUN sed -i 's/Components: main/Components: main contrib/' /etc/apt/sources.list.d/debian.sources \
 && echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections \
 && apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates tzdata curl \
    libreoffice-writer \
    fonts-liberation fonts-dejavu-core \
    ttf-mscorefonts-installer \
 && fc-cache -f \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# Zona horaria (Cd. Juárez)
RUN ln -snf /usr/share/zoneinfo/America/Chihuahua /etc/localtime && \
    echo "America/Chihuahua" > /etc/timezone && \
    dpkg-reconfigure -f noninteractive tzdata

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencias Python
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Colocamos archivos que no deben ser pisados por el bind mount
COPY docker/backend/entrypoint.sh /usr/local/bin/agenda-entrypoint
COPY docker/backend/gunicorn.conf.py /etc/gunicorn/gunicorn.conf.py
RUN chmod +x /usr/local/bin/agenda-entrypoint

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/agenda-entrypoint"]
