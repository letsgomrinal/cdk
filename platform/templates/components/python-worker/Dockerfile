FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"

# Dependencies first (cached layer), from the lockfile only. --locked fails the
# build if uv.lock is out of date with pyproject.toml: run `uv lock` and commit.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .
ENTRYPOINT ["python", "main.py"]
