FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY ralph_wiggum /app/ralph_wiggum

RUN pip install --no-cache-dir -e .

CMD ["python", "-m", "ralph_wiggum.cli", "audit", "."]
