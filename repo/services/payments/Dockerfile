# TicketHub Payments service — Python stdlib stub, non-root (Ch 10).
FROM python:3.12-slim
WORKDIR /app
COPY app.py .
RUN useradd --uid 65532 --no-create-home --shell /usr/sbin/nologin nonroot
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["python", "app.py"]
