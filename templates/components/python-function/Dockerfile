# Built as a normal container like every other component, so build, release
# and promotion work the same way for functions.
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"

# Dependencies first (cached layer), from the lockfile only. --locked fails the
# build if uv.lock is out of date with pyproject.toml: run `uv lock` and commit.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .
CMD exec functions-framework --target=handle --signature-type=cloudevent --port=${PORT:-8080}
