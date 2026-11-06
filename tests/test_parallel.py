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
