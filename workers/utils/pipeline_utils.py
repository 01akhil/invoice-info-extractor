from pathlib import Path

def list_image_files(folder: Path) -> list[Path]:
    exts = {".jpg", ".jpeg", ".png"}
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in exts)

def reset_human_review_queue(path: Path) -> None:
    path.write_text("[]", encoding="utf-8")