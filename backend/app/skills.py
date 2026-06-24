from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(prefix="/skills", tags=["skills"])


@dataclass(frozen=True)
class SkillTarget:
    id: str
    label: str
    path: Path


class SkillSyncRequest(BaseModel):
    target_ids: list[str] | None = None


def default_targets() -> list[SkillTarget]:
    home = user_home()
    return [
        SkillTarget(id="agents", label="Agents", path=target_path("INGESTOR_AGENTS_SKILLS_DIR", home / ".agents" / "skills")),
        SkillTarget(id="codex", label="Codex", path=target_path("INGESTOR_CODEX_SKILLS_DIR", home / ".codex" / "skills")),
        SkillTarget(id="claude", label="Claude", path=target_path("INGESTOR_CLAUDE_SKILLS_DIR", home / ".claude" / "skills")),
    ]


@router.get("/targets")
def skill_targets() -> dict:
    source_skills = list_source_skills()
    return {
        "source_dir": str(source_skills_dir()),
        "skills": source_skills,
        "targets": [target_status(target, source_skills) for target in default_targets()],
    }


@router.post("/sync")
def sync_skills(request: SkillSyncRequest | None = None) -> dict:
    source_skills = list_source_skills()
    if not source_skills:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No app-owned skills were found.")

    requested = set(request.target_ids or [target.id for target in default_targets()])
    targets = [target for target in default_targets() if target.id in requested]
    if not targets:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No supported skill targets were selected.")

    synced_targets = []
    for target in targets:
        target.path.mkdir(parents=True, exist_ok=True)
        for skill in source_skills:
            copy_skill(skill["name"], target.path)
        synced_targets.append(target_status(target, source_skills))

    return {
        "source_dir": str(source_skills_dir()),
        "skills": source_skills,
        "targets": synced_targets,
    }


def source_skills_dir() -> Path:
    configured = os.environ.get("INGESTOR_SKILLS_DIR")
    if configured:
        return Path(os.path.expandvars(configured)).expanduser()
    return get_settings().project_root.parent / "skills"


def user_home() -> Path:
    return Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or str(Path.home())).expanduser()


def target_path(env_key: str, fallback: Path) -> Path:
    configured = os.environ.get(env_key)
    if not configured:
        return fallback
    return Path(os.path.expandvars(configured)).expanduser()


def list_source_skills() -> list[dict]:
    root = source_skills_dir()
    if not root.exists():
        return []
    skills = []
    for skill_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            skills.append(
                {
                    "name": skill_dir.name,
                    "path": str(skill_dir),
                    "hash": file_hash(skill_file),
                }
            )
    return skills


def target_status(target: SkillTarget, source_skills: list[dict]) -> dict:
    installed = []
    for skill in source_skills:
        target_skill = target.path / skill["name"]
        target_skill_file = target_skill / "SKILL.md"
        installed_hash = file_hash(target_skill_file) if target_skill_file.exists() else None
        installed.append(
            {
                "name": skill["name"],
                "installed": target_skill_file.exists(),
                "current": installed_hash == skill["hash"],
                "path": str(target_skill),
            }
        )

    return {
        "id": target.id,
        "label": target.label,
        "path": str(target.path),
        "exists": target.path.exists(),
        "skills": installed,
        "current": bool(installed) and all(skill["current"] for skill in installed),
    }


def copy_skill(name: str, target_root: Path) -> None:
    source = source_skills_dir() / name
    if not source.exists():
        raise FileNotFoundError(f"Skill not found: {name}")

    target = target_root / name
    shutil.copytree(source, target, dirs_exist_ok=True)
    manifest = {
        "managed_by": "ingestor",
        "source": str(source),
        "skill": name,
        "skill_hash": file_hash(source / "SKILL.md"),
    }
    (target / ".ingestor-skill.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
