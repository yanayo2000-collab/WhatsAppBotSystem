from whatsapp_bot_system.templates import (
    BotPersona,
    ScenarioTemplate,
    TemplateCatalog,
    render_candidate_from_template,
)


def test_render_welcome_template_uses_persona_and_context():
    catalog = TemplateCatalog(
        personas={
            'bot-welcome': BotPersona(
                bot_id='bot-welcome',
                display_name='Luna',
                tone='warm',
                style_hint='friendly and encouraging',
            )
        },
        scenarios={
            'welcome': ScenarioTemplate(
                scenario_id='welcome',
                template='Hi {{group_name}} friends, I\'m {{bot_name}}. {{rules_summary}}',
            )
        },
    )

    rendered = render_candidate_from_template(
        catalog=catalog,
        bot_id='bot-welcome',
        scenario_id='welcome',
        context={
            'group_name': 'Moms Club',
            'rules_summary': 'Please read the pinned guide.',
        },
    )

    assert rendered.bot_display_name == 'Luna'
    assert rendered.scenario_id == 'welcome'
    assert 'Moms Club' in rendered.text
    assert 'pinned guide' in rendered.text
    assert rendered.metadata['tone'] == 'warm'


def test_render_falls_back_to_default_template_when_missing_scenario_template():
    catalog = TemplateCatalog(
        personas={
            'bot-icebreaker': BotPersona(
                bot_id='bot-icebreaker',
                display_name='Mia',
                tone='playful',
                style_hint='light and chatty',
            )
        },
        scenarios={},
    )

    rendered = render_candidate_from_template(
        catalog=catalog,
        bot_id='bot-icebreaker',
        scenario_id='cold_start',
        context={'topic_hint': 'today\'s side hustle tips'},
    )

    assert rendered.bot_display_name == 'Mia'
    assert 'side hustle' in rendered.text
    assert rendered.metadata['template_source'] == 'fallback'


def test_catalog_can_be_loaded_from_dict():
    catalog = TemplateCatalog.from_dict(
        {
            'personas': {
                'bot-welcome': {
                    'display_name': 'Luna',
                    'tone': 'warm',
                    'style_hint': 'friendly and encouraging',
                }
            },
            'scenarios': {
                'welcome': {
                    'template': 'Hi {{group_name}} friends, I\'m {{bot_name}}.'
                }
            },
        }
    )

    assert catalog.personas['bot-welcome'].display_name == 'Luna'
    assert catalog.scenarios['welcome'].template.startswith('Hi')
