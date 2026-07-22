from datetime import datetime, timedelta

from scheduler import JobDefinition, JobState, build_command


def make_job(**overrides):
    values = dict(
        name="demo",
        script_path=r"C:\Work Folder\job.py",
        setup_commands="call .venv\\Scripts\\activate.bat\nset MODE=test",
        start_at=datetime.now() + timedelta(minutes=1),
        stop_at=datetime.now() + timedelta(minutes=2),
    )
    values.update(overrides)
    return JobDefinition(**values)


def test_command_appends_script_and_arguments():
    command = build_command(make_job(script_arguments="--days 3"))
    assert command.endswith('python -u "C:\\Work Folder\\job.py" --days 3')
    assert "activate.bat" in command
    assert " & " in command


def test_default_job_is_queued():
    assert make_job().state is JobState.QUEUED
    assert make_job().allow_parallel is False


def test_empty_setup_is_supported():
    assert build_command(make_job(setup_commands="")) == 'python -u "C:\\Work Folder\\job.py"'


def test_selected_environment_is_activated_before_setup():
    command = build_command(make_job(environment="C:\\Miniconda3\\envs\\demo"))
    assert 'activate "C:\\Miniconda3\\envs\\demo"' in command
    assert command.endswith('python -u "C:\\Work Folder\\job.py"')
