FROM python:3.11-slim

WORKDIR /app

COPY flight_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Generate gRPC code from proto
COPY proto/ /app/proto/
RUN python -m grpc_tools.protoc \
    -I/app/proto \
    --python_out=/app \
    --grpc_python_out=/app \
    /app/proto/flight.proto

COPY flight_service/ /app/

EXPOSE 50051

CMD ["python", "main.py"]
