FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS runtime

WORKDIR /workspace
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy

COPY packages packages
COPY services services
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --all-packages
ENV PATH="/workspace/.venv/bin:$PATH"
