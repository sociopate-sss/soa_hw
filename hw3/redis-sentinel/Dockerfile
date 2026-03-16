FROM redis:7

COPY sentinel.conf /tmp/sentinel.conf

CMD ["redis-sentinel", "/tmp/sentinel.conf"]
