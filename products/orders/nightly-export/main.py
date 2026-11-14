"""Cloud Run job task. Runs to completion; non-zero exit = failed task (retried per max_retries)."""
import os
import sys


def main(args):
    task = int(os.environ.get("CLOUD_RUN_TASK_INDEX", 0))
    count = int(os.environ.get("CLOUD_RUN_TASK_COUNT", 1))
    print(f"orders/nightly-export task {task + 1}/{count} args={args}")


if __name__ == "__main__":
    main(sys.argv[1:])
