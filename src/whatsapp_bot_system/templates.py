from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from whatsapp_bot_system.runtime import CandidateMessage, create_candidate_message


@dataclass(frozen=True)
class BotPersona:
    bot_id: str
    display_name: str
    tone: str = 'neutral'
    style_hint: str = ''


@dataclass(frozen=True)
class ScenarioTemplate:
    scenario_id: str
    template: str


@dataclass(frozen=True)
class TemplateCatalog:
    personas: dict[str, BotPersona] = field(default_factory=dict)
    scenarios: dict[str, ScenarioTemplate] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> 'TemplateCatalog':
        personas = {
            bot_id: BotPersona(
                bot_id=bot_id,
                display_name=str(config.get('display_name') or bot_id),
                tone=str(config.get('tone') or 'neutral'),
                style_hint=str(config.get('style_hint') or ''),
            )
            for bot_id, config in (payload.get('personas') or {}).items()
            if isinstance(config, dict)
        }
        scenarios = {
            scenario_id: ScenarioTemplate(
                scenario_id=scenario_id,
                template=str(config.get('template') or '').strip(),
            )
            for scenario_id, config in (payload.get('scenarios') or {}).items()
            if isinstance(config, dict)
        }
        return cls(personas=personas, scenarios=scenarios)


def render_candidate_from_template(
    *,
    catalog: TemplateCatalog,
    bot_id: str,
    scenario_id: str,
    context: dict[str, Any] | None = None,
) -> CandidateMessage:
    payload = dict(context or {})
    persona = catalog.personas.get(bot_id, BotPersona(bot_id=bot_id, display_name=bot_id))
    template = catalog.scenarios.get(scenario_id)
    payload.setdefault('bot_name', persona.display_name)
    payload.setdefault('tone', persona.tone)
    payload.setdefault('style_hint', persona.style_hint)

    if template and template.template:
        text = _render_simple_template(template.template, payload)
        return CandidateMessage(
            scenario_id=scenario_id,
            bot_display_name=persona.display_name,
            content_mode='template_rewrite',
            text=text,
            metadata={
                'tone': persona.tone,
                'style_hint': persona.style_hint,
                'template_source': 'catalog',
            },
        )

    fallback = create_candidate_message(
        scenario_id=scenario_id,
        bot_display_name=persona.display_name,
        content_mode='template_rewrite',
        context=payload,
    )
    return CandidateMessage(
        scenario_id=fallback.scenario_id,
        bot_display_name=fallback.bot_display_name,
        content_mode=fallback.content_mode,
        text=fallback.text,
        metadata={
            'tone': persona.tone,
            'style_hint': persona.style_hint,
            'template_source': 'fallback',
        },
    )


def _render_simple_template(template: str, context: dict[str, Any]) -> str:
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace('{{' + key + '}}', str(value))
    return rendered
