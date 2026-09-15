"""Hermes plugin generated from the shared agent skill pack."""

from pathlib import Path


def register(ctx):
    base_dir = Path(__file__).parent
    # Hermes exposes these as namespaced skills, e.g. plugin-name:skill-name.
    ctx.register_skill('ai-native-core-starter-kit', base_dir / 'skills' / 'ai-native-core-starter-kit' / 'SKILL.md')
    ctx.register_skill('ai-native-proposal', base_dir / 'skills' / 'ai-native-proposal' / 'SKILL.md')
    ctx.register_skill('architect', base_dir / 'skills' / 'architect' / 'SKILL.md')
    ctx.register_skill('smd-drawio', base_dir / 'skills' / 'smd-drawio' / 'SKILL.md')
    ctx.register_skill('func-arch-drawio', base_dir / 'skills' / 'func-arch-drawio' / 'SKILL.md')
    ctx.register_skill('eepc-drawio', base_dir / 'skills' / 'eepc-drawio' / 'SKILL.md')
    ctx.register_skill('comind-docx', base_dir / 'skills' / 'comind-docx' / 'SKILL.md')
    ctx.register_skill('editorial-style', base_dir / 'skills' / 'editorial-style' / 'SKILL.md')
    ctx.register_skill('sequential-thinking', base_dir / 'skills' / 'sequential-thinking' / 'SKILL.md')
    ctx.register_skill('document-templates', base_dir / 'skills' / 'document-templates' / 'SKILL.md')
