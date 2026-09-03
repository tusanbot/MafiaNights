# Runtime is pinned to the Python version declared by pyproject.toml.
FROM python:3.12-slim

WORKDIR /Mafia

COPY requirements.txt .

RUN apt-get update && apt-get install -y --no-install-recommends gcc libffi-dev \
    && pip install --upgrade pip \
    && pip install -r requirements.txt \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip show aiogram

CMD ["python", "player_runtime_entry.py"]
