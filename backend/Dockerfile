# Backend image for the AI Traffic Management System.
#
# Two stages: dependencies are installed once into a virtualenv that the runtime
# stage copies wholesale, so no compiler ends up in the shipped image.
#
# Build:  docker build -t traffic-backend ./backend
# Run:    docker run -p 8000:8000 traffic-backend

# ---------------------------------------------------------------- builder ---
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install --no-install-recommends -y \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# A virtualenv keeps our dependencies separate from the system Python, which
# makes the copy into the runtime stage a single self-contained directory.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt .

# The CPU-only torch wheel is ~200 MB against ~3 GB for the CUDA build. Pass
# --build-arg TORCH_INDEX_URL= to use the default index, or point it at a CUDA
# index for a GPU image.
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN pip install --upgrade pip \
    && if [ -n "$TORCH_INDEX_URL" ]; then \
         pip install --index-url "$TORCH_INDEX_URL" torch torchvision \
         || echo "CPU wheel index unreachable; falling back to the default index"; \
       fi \
    && pip install -r requirements.txt

# ---------------------------------------------------------------- runtime ---
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    ENVIRONMENT=production

# libGL and libglib are required by OpenCV even in its headless build;
# curl backs the container healthcheck.
RUN apt-get update && apt-get install --no-install-recommends -y \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

COPY --from=builder /opt/venv /opt/venv

# Run unprivileged: a process that only reads code and writes to a few data
# directories has no business running as root.
RUN groupadd --system traffic && useradd --system --gid traffic --home /app traffic

WORKDIR /app
RUN mkdir -p /app/models /app/uploads /app/output_images /app/logs /app/data \
    && chown -R traffic:traffic /app

COPY --chown=traffic:traffic ./app ./app

USER traffic

EXPOSE 8000

# start-period is generous: the first boot downloads the model weights.
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# One uvicorn worker by default. The signal controller holds per-process state,
# so scaling means one process per intersection group behind a proxy, not
# several workers sharing a port.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
