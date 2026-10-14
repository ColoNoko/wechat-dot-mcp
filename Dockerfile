FROM python:3.11.14-slim-bookworm@sha256:65a93d69fa75478d554f4ad27c85c1e69fa184956261b4301ebaf6dbb0a3543d AS dependencies
COPY requirements.lock /build/requirements.lock
COPY vendor/wheels/ /build/wheels/
RUN python -m pip install --no-cache-dir --no-index --find-links=/build/wheels --require-hashes --prefix=/install -r /build/requirements.lock

FROM python:3.11.14-slim-bookworm@sha256:65a93d69fa75478d554f4ad27c85c1e69fa184956261b4301ebaf6dbb0a3543d
LABEL org.opencontainers.image.title="WeChat Dot Bridge (private NAS)" \
      org.opencontainers.image.source="https://github.com/cd233ljx/wechat-dot-bridge" \
      org.opencontainers.image.revision="67c726e15ae2de8b60d293d6f5e81107bd0b6ebc" \
      org.opencontainers.image.version="0.1.0-67c726e-tunnel0.0.16-nas1"
COPY --from=dependencies /install/ /usr/local/
COPY source/wechat_dot_bridge/ /opt/bridge/wechat_dot_bridge/
COPY source/scripts/ /opt/bridge/scripts/
COPY source/licenses/ /opt/bridge/licenses/
COPY source/LICENSE source/NOTICE.txt source/pyproject.toml source/uv.lock /opt/bridge/
COPY vendor/tunnel/ /opt/tunnel/
COPY container/ /opt/container/
RUN chmod -R a+rX /opt \
    && chmod 755 /opt/tunnel/tunnel-client /opt/tunnel/cloudflared /opt/container/wechat-dot-bridge \
    && ln -s /opt/container/wechat-dot-bridge /usr/local/bin/wechat-dot-bridge \
    && mkdir -p /config /run/secrets /state \
    && chown 1000:1000 /state && chmod 700 /state
ENV PYTHONPATH=/opt/bridge PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HOME=/state/home TINI_KILL_PROCESS_GROUP=1
WORKDIR /opt/bridge
USER 1000:1000
STOPSIGNAL SIGTERM
ENTRYPOINT ["python", "/opt/container/entrypoint.py"]
CMD ["run"]
