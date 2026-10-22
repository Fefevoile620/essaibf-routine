from mistralai.workflows import run_worker

from routine import EssaibfRoutine

if __name__ == "__main__":
    run_worker([EssaibfRoutine])
