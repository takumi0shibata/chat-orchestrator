FROM python:3.12-slim-bookworm
ENV DEBIAN_FRONTEND=noninteractive UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ripgrep findutils coreutils file unzip zip libreoffice \
    fonts-noto-cjk fontconfig poppler-utils libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.10.12
WORKDIR /opt/runtime
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
ENV PATH="/opt/runtime/.venv/bin:$PATH" \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 \
    PYTHONDONTWRITEBYTECODE=1 HOME=/tmp MPLCONFIGDIR=/tmp/matplotlib
RUN mkdir -p /workspace /input /skills /resources && chmod 755 /opt/runtime
USER 1000:1000
WORKDIR /workspace
CMD ["sleep", "infinity"]
