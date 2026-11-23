# Database bootstrap job image. Built on the non-prod pool, signed, promoted by digest.
FROM python:3.15-slim AS build
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --target /deps -r requirements.txt

FROM gcr.io/distroless/python3-debian12:nonroot
WORKDIR /app
COPY --from=build /deps /deps
COPY bootstrap.py .
ENV PYTHONPATH=/deps PYTHONUNBUFFERED=1
ENTRYPOINT ["python3", "/app/bootstrap.py"]
