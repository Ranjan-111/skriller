ARG WORKER_BASE=skriller-egress-worker-bookworm@sha256:1f545e03d388697e527d64bcf573d3a91a7d0a52457fca2b14923c9bdbd9cc68
FROM ${WORKER_BASE}
COPY infra/egress/x-requirements.txt /app/x-requirements.txt
COPY --from=x_wheels . /tmp/x-wheels
RUN cd /tmp/x-wheels && sha256sum -c SHA256SUMS \
    && pip install --no-index --find-links=/tmp/x-wheels --no-deps -r /app/x-requirements.txt \
    && rm -rf /tmp/x-wheels
COPY src/skriller /app/src/skriller
COPY third_party/scrapling/LICENSE /app/licenses/Scrapling-LICENSE
ENV PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1 SKRILLER_X_WORKER=isolated
ENTRYPOINT ["/usr/local/bin/guarded-worker"]
