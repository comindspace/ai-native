"""Hermes root plugin for the company-agent-skills repository."""

import shutil
from pathlib import Path


PLUGIN_NAME = 'company-agent-skills'


PACKS = {
    'ai-native-core': ['ai-native-core-starter-kit', 'ai-native-proposal', 'architect', 'smd-drawio', 'func-arch-drawio', 'eepc-drawio', 'comind-docx', 'editorial-style', 'sequential-thinking', 'document-templates'],
}


def _get_profile_skills_root():
    try:
        from hermes_constants import get_hermes_home
        return get_hermes_home() / 'skills' / PLUGIN_NAME
    except Exception:
        return None


def _mirror_skill_for_web_ui(skill, skill_dir):
    skills_root = _get_profile_skills_root()
    if skills_root is None:
        return
    target = skills_root / skill
    try:
        skills_root.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            if target.resolve() == skill_dir.resolve():
                return
            target.unlink()
        elif target.exists():
            shutil.rmtree(target)
        try:
            target.symlink_to(skill_dir, target_is_directory=True)
        except OSError:
            shutil.copytree(skill_dir, target, dirs_exist_ok=True)
    except Exception:
        return


def register(ctx):
    base_dir = Path(__file__).parent
    seen = set()
    for pack_name, skills in PACKS.items():
        pack_dir = base_dir / 'plugins' / pack_name
        for skill in skills:
            skill_dir = pack_dir / 'skills' / skill
            if skill in seen or not (skill_dir / 'SKILL.md').exists():
                continue
            ctx.register_skill(skill, skill_dir / 'SKILL.md')
            _mirror_skill_for_web_ui(skill, skill_dir)
            seen.add(skill)
