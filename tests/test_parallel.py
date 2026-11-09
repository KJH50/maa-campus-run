import logging

from maa_campus import parallel


def test_aggregate_exit():
    assert parallel.aggregate_exit([0, 0]) == 0
    assert parallel.aggregate_exit([0, 2]) == 2
    assert parallel.aggregate_exit([2, 3]) == 3
    assert parallel.aggregate_exit([1, 0]) == 1
    assert parallel.aggregate_exit([]) == 1


def test_build_child_cmd_flags():
    cmd = parallel.build_child_cmd("cfg.json", dry=True, skip_start=True, force=True)
    assert "--now" in cmd
    assert "--dry" in cmd
    assert "--wait-finish" in cmd
    assert "--force" in cmd
    assert cmd[cmd.index("--config") + 1] == "cfg.json"
    assert cmd[0].endswith(("python.exe", "python"))
    assert cmd[1].endswith("run.py")


def test_build_child_cmd_defaults():
    cmd = parallel.build_child_cmd("cfg.json", dry=False, skip_start=False, force=False)
    assert "--dry" not in cmd
    assert "--wait-finish" not in cmd
    assert "--force" not in cmd
    assert "--no-record" not in cmd


def test_build_child_cmd_no_record():
    cmd = parallel.build_child_cmd("cfg.json", dry=False, skip_start=False, force=True,
                                   record=False)
    assert "--force" in cmd
    assert "--no-record" in cmd


def test_stagger_delay():
    assert parallel._stagger_delay({"instance_start_stagger_seconds": 20}, 0) == 0
    assert parallel._stagger_delay({"instance_start_stagger_seconds": 20}, 1) == 20
    assert parallel._stagger_delay({"instance_start_stagger_seconds": 20}, 2) == 40
    assert parallel._stagger_delay({"instance_start_stagger_seconds": 0}, 2) == 0
    assert parallel._stagger_delay({}, 1) == 20  # 默认 20 秒


def test_run_parallel_staggers_instances(monkeypatch):
    sleeps = []

    class FakePopen:
        def __init__(self, *args, **kwargs):
            self.stdout = iter(())
            self.returncode = 0

        def wait(self):
            return 0

    monkeypatch.setattr(parallel.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(parallel.time, "sleep", lambda seconds: sleeps.append(seconds))
    cfg = {"instances": [{"name": "mumu-1", "adb_serial": "127.0.0.1:16416", "mumu_index": 1},
                         {"name": "mumu-2", "adb_serial": "127.0.0.1:16448", "mumu_index": 2}],
           "instance_start_stagger_seconds": 20}
    assert parallel.run_parallel(cfg, logging.getLogger("t"), "cfg.json") == 0
    assert sleeps == [20]
