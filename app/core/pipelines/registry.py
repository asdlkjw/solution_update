from typing import Any, Callable, Dict

_REGISTRY: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}


def register_pipeline(version: str, process_fn: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
    _REGISTRY[version] = process_fn


def get_pipeline(version: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    if version not in _REGISTRY:
        raise ValueError(f"Unknown pipeline version: {version}. Available: {list(_REGISTRY.keys())}")
    return _REGISTRY[version]


def available_versions() -> list[str]:
    return list(_REGISTRY.keys())
