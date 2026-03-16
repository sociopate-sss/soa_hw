FROM python:3.11-slim

WORKDIR /app

COPY booking_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Generate gRPC code from proto
COPY proto/ /app/proto/
RUN python -m grpc_tools.protoc \
    -I/app/proto \
    --python_out=/app \
    --grpc_python_out=/app \
    /app/proto/flight.proto

COPY booking_service/ /app/

EXPOSE 8080

CMD ["python", "main.py"]
