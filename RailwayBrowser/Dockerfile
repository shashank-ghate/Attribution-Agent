FROM lscr.io/linuxserver/chromium:latest

RUN apt-get update \
    && apt-get install -y --no-install-recommends socat \
    && rm -rf /var/lib/apt/lists/*

COPY RailwayBrowser/cdp-forward /custom-services.d/cdp-forward
RUN chmod 0755 /custom-services.d/cdp-forward
