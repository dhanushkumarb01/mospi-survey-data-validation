"""Traceable evidence fusion and supervisor-review support for MoSPI."""

__all__ = ["FusionEngine", "FusionFailure", "RunConfig"]


def __getattr__(name: str):
    # Imported on first use, so serving code that needs only labels, explanations or the review store (the hosted
    # instance) does not load the batch engine and its scientific dependencies.
    if name in __all__:
        from . import engine
        return getattr(engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
