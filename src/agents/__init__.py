"""Agent package. Prefer `from src.agents.ant import WorkerAnt`."""

__all__ = ["WorkerAnt"]


def __getattr__(name: str):
    if name == "WorkerAnt":
        from .ant import WorkerAnt

        return WorkerAnt
    raise AttributeError(name)
