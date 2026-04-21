from pathlib import Path

from whatsapp_bot_system.app import create_app_from_config_path


def test_create_app_from_config_path_uses_yaml_settings(tmp_path):
    config_path = tmp_path / 'config.yaml'
    config_path.write_text(
        'database:\n'
        '  review_db_path: "' + str((tmp_path / 'review.db')).replace('\\', '/') + '"\n'
        '  execution_db_path: "' + str((tmp_path / 'execution.db')).replace('\\', '/') + '"\n'
        'execution:\n'
        '  default_sender: dry_run\n'
        'templates:\n'
        '  personas:\n'
        '    bot-welcome:\n'
        '      display_name: Luna\n'
        '  scenarios:\n'
        '    welcome:\n'
        '      template: "Hi {{group_name}} friends, I\'m {{bot_name}}."\n',
        encoding='utf-8',
    )

    app = create_app_from_config_path(config_path)

    assert app.title == 'WhatsApp Bot System'
