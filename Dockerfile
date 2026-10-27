FROM python:3.14-slim

COPY pyproject.toml README.md LICENSE /src/
COPY src /src/src
RUN pip install --no-cache-dir /src && rm -rf /src

# the shades cache, mount a volume to keep it
ENV SOMA_CACHE_FILE=/data/shades.json
VOLUME /data

# bleak talks to the BlueZ daemon of the host over D-Bus, mount /run/dbus of the host
ENTRYPOINT ["soma"]
CMD ["bridge"]
