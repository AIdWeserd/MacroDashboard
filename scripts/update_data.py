"""Последовательные обновления в отдельном Linux-контейнере, без cron в web."""

import os
import signal
import subprocess
import sys
import threading


def positive_seconds(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} должен быть положительным числом секунд")
    return value


def run_once(timeout: int) -> int:
    # Kill the process group too: some fetchers start an MCP subprocess.
    process = subprocess.Popen(
        [sys.executable, "scheduler.py"], start_new_session=True,
    )
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        print("[ERROR] Превышено время обновления", flush=True)
        return 124
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def main() -> None:
    # flock is Linux-specific; keeping this import here permits portable unit tests.
    import fcntl
    from config import DATA_DIR

    interval = positive_seconds("MACRO_UPDATE_INTERVAL", 21600)
    timeout = positive_seconds("MACRO_UPDATE_TIMEOUT", 14400)
    stopped = threading.Event()

    def stop(signum, frame):
        stopped.set()
        # Interrupt wait() so run_once's finally terminates the child group.
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with (DATA_DIR / ".update.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Другой updater уже использует этот каталог данных")
        while not stopped.is_set():
            result = run_once(timeout)
            print(f"[UPDATE] scheduler exit={result}; следующий запуск через {interval} с", flush=True)
            stopped.wait(interval)


if __name__ == "__main__":
    main()
