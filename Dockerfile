FROM python:3.10

# تثبيت المتطلبات + Tor للتمويه
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6 \
    git \
    libmagic1 \
    ca-certificates \
    curl \
    tor \
    torsocks \
    && rm -rf /var/lib/apt/lists/*

RUN update-ca-certificates

# إعداد Tor ليشتغل بدون Root
RUN mkdir -p /var/run/tor /var/lib/tor && \
    chmod 777 /var/run/tor /var/lib/tor

# Hugging Face محتاج يوزر برقم 1000
RUN useradd -m -u 1000 user

# إعداد ملف Tor مبسط يعمل بيوزر عادي
RUN echo "SocksPort 9050\nDataDirectory /home/user/tor-data\nLog notice stdout" > /home/user/torrc && \
    mkdir -p /home/user/tor-data && \
    chown -R user:user /home/user/torrc /home/user/tor-data

USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

ENV PYTHONUNBUFFERED=1

# سكريبت تشغيل Tor ثم البوت
CMD ["bash", "-c", "tor -f /home/user/torrc & sleep 5 && python main.py"]
