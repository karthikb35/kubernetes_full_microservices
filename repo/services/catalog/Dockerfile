# TicketHub Catalog service — Python stdlib stub, non-root (Ch 10).
FROM python:3.12-slim
WORKDIR /app
COPY app.py .
# Run as a non-root user (pairs with runAsNonRoot, Ch 20).
RUN useradd --uid 65532 --no-create-home --shell /usr/sbin/nologin nonroot
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["python", "app.py"]
