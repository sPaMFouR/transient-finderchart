from __future__ import annotations

from pathlib import Path

from .models import Target


def ensure_export_suffix(path: Path, selected_filter: str) -> Path:
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf"}:
        return path
    if selected_filter.startswith("JPEG"):
        return path.with_suffix(".jpg")
    if selected_filter.startswith("PDF"):
        return path.with_suffix(".pdf")
    return path.with_suffix(".png")


def default_export_filename(target: Target) -> str:
    preferred_name = next((alias for alias in target.aliases if alias.strip()), target.label)
    return f"findingchart_{safe_filename_part(preferred_name)}.jpg"


def safe_filename_part(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "target"
