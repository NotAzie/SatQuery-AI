FROM python:3.12-slim

WORKDIR /app
COPY engine/satquery-ai/ .
RUN python -m pip install --no-cache-dir ".[geospatial,raster]"

EXPOSE 8000
CMD ["python", "-m", "satquery", "serve", "--host", "0.0.0.0", "--port", "8000"]
