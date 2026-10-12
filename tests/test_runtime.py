from skriller.research import runtime


def test_macos_local_worker_avoids_spawn_trace_and_unsupported_broker_control(monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    args = runtime.worker_arguments([])
    assert "--pool=solo" in args and "--concurrency=1" in args
    assert "--without-mingle" in args and "--without-gossip" in args


def test_linux_worker_retains_process_isolation_and_explicit_pool_option(monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    assert "--pool=prefork" in runtime.worker_arguments([])
    assert "--pool=solo" in runtime.worker_arguments(["--pool", "solo"])
