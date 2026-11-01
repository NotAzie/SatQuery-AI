FROM python:3.12-slim

WORKDIR /app
COPY APP/backend/ ./backend/
COPY APP/config/ ./config/
RUN python -m pip install --no-cache-dir ./backend

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "earth_platform.main:create_app", "--factory", "--app-dir", "backend/src", "--host", "0.0.0.0", "--port", "8000"]
