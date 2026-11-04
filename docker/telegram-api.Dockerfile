FROM debian:bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git cmake g++ make gperf libssl-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
ARG TELEGRAM_API_REF=e3e9dd8e5b3d7ab8537cd5a10dc31d5ffa8f82d1
RUN git clone --recursive https://github.com/tdlib/telegram-bot-api.git /src \
    && cd /src && git checkout "$TELEGRAM_API_REF" && git submodule update --init --recursive
RUN cmake -S /src -B /src/build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /src/build --target telegram-bot-api -j2
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libssl3 zlib1g curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 audioapp && useradd -u 10001 -g audioapp -m audioapp \
    && mkdir /telegram && chown 10001:10001 /telegram
COPY --from=build /src/build/telegram-bot-api /usr/local/bin/telegram-bot-api
COPY docker/start-api.sh /usr/local/bin/start-api
RUN chmod 755 /usr/local/bin/start-api
USER 10001:10001
ENTRYPOINT ["/usr/local/bin/start-api"]
