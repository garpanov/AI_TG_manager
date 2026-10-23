FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends git cmake build-essential \
    && git clone --depth 1 --branch v1.7.6 https://github.com/ggerganov/whisper.cpp.git /whisper.cpp \
    && cmake -S /whisper.cpp -B /whisper.cpp/build \
        -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_EXAMPLES=ON \
        -DGGML_NATIVE=OFF -DBUILD_SHARED_LIBS=OFF \
    && cmake --build /whisper.cpp/build --config Release -j2

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /whisper.cpp/build/bin/whisper-cli /usr/local/bin/whisper-cli
WORKDIR /workspace
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
COPY packages packages
COPY services services
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --package ai-manager-voice
ENV PATH="/workspace/.venv/bin:$PATH"
CMD ["ai-manager-voice"]
