from app.workers.tasks import ping


def test_ping_task_runs_eagerly_in_dev():
    assert ping.delay().get(timeout=5) == "pong"
