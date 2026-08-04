FROM lscr.io/linuxserver/chromium:latest

# The base image includes an s6 watchdog which relaunches its autostart command
# when Chromium exits. It is opt-in, so keep it enabled for unattended jobs.
ENV RESTART_APP=true

RUN apt-get update \
    && apt-get install -y --no-install-recommends socat \
    && rm -rf /var/lib/apt/lists/*

COPY RailwayBrowser/cdp-forward /custom-services.d/cdp-forward
RUN chmod 0755 /custom-services.d/cdp-forward
