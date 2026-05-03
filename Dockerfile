FROM python:3.10-slim

# Install minimal system dependencies
RUN apt-get update && apt-get install -y \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# HF Spaces requires user with UID 1000
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

ENV PYTHONUNBUFFERED=1

# HF Spaces health check port
EXPOSE 7860

CMD ["python", "main.py"]
