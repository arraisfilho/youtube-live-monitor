FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --system --uid 10001 --home-dir /var/lib/youtube-live-monitor monitor \
    && install -d -o monitor -g monitor /var/lib/youtube-live-monitor
COPY youtube_live_monitor.py .
USER monitor
EXPOSE 9877
ENTRYPOINT ["python", "/app/youtube_live_monitor.py"]
CMD ["--config", "/etc/youtube-live-monitor/config.yaml", "--database", "/var/lib/youtube-live-monitor/state.db"]
