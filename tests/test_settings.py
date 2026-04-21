from pathlib import Path

from whatsapp_bot_system.settings import AppSettings, load_settings


def test_load_settings_from_yaml(tmp_path):
    config_path = tmp_path / 'config.yaml'
    config_path.write_text(
        'database:\n'
        '  review_db_path: data/review_flow.db\n'
        '  execution_db_path: data/execution_attempts.db\n'
        'execution:\n'
        '  default_sender: webhook\n'
        '  webhook_sender:\n'
        '    endpoint: http://127.0.0.1:9999/send\n'
        'api:\n'
        '  host: 127.0.0.1\n'
        '  port: 8799\n'
        'templates:\n'
        '  personas:\n'
        '    bot-welcome:\n'
        '      display_name: Luna\n'
        '      tone: warm\n'
        '      style_hint: friendly and encouraging\n'
        '  scenarios:\n'
        '    welcome:\n'
        '      template: "Hi {{group_name}} friends, I\'m {{bot_name}}."\n',
        encoding='utf-8',
    )

    settings = load_settings(config_path)

    assert isinstance(settings, AppSettings)
    assert settings.execution.default_sender == 'webhook'
    assert settings.execution.webhook_sender.endpoint == 'http://127.0.0.1:9999/send'
    assert settings.templates['personas']['bot-welcome']['display_name'] == 'Luna'


def test_load_settings_defaults_when_file_missing(tmp_path):
    settings = load_settings(tmp_path / 'missing.yaml')

    assert settings.execution.default_sender == 'mock'
    assert settings.database.review_db_path == 'data/review_flow.db'
