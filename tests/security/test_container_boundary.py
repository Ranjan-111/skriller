"""Opt-in kernel/filesystem gate; never silently replace it with URL unit tests."""

import os
import subprocess
import uuid

import pytest


@pytest.mark.integration_db
def test_real_worker_cannot_bypass_proxy_or_read_host_files(tmp_path):
    if os.environ.get("SKRILLER_EGRESS_CONTAINER_TESTS") != "1":
        pytest.skip("Requires built isolated worker fixture and running guarded proxy network")
    sentinel = tmp_path / "host-only-secret"
    sentinel.write_text("must never be visible inside the worker")
    code = """
import os,socket,sys,pathlib,subprocess
assert os.getuid() != 0
assert 'CapEff:\\t0000000000000000' in pathlib.Path('/proc/self/status').read_text()
assert not pathlib.Path(sys.argv[1]).exists()
assert not pathlib.Path('/var/run/docker.sock').exists()
assert os.getenv('SKRILLER_HOST_ONLY_SECRET') is None
try:
    pathlib.Path('/etc/skriller-write-test').write_text('denied')
except OSError:
    pass
else:
    raise AssertionError('root filesystem was writable')
for address in ('169.254.169.254','10.0.0.1','1.1.1.1','127.0.0.1'):
    connection=socket.socket()
    connection.settimeout(.3)
    try:
        connection.connect((address,80))
    except OSError:
        pass
    else:
        raise AssertionError('direct egress escaped firewall: '+address)
    finally:
        connection.close()
# A listening loopback service distinguishes firewall denial from lack of a
# server, and UDP covers routes browsers could use outside HTTP proxy settings.
listener=socket.socket()
listener.bind(('127.0.0.1',0))
listener.listen(1)
connection=socket.socket()
connection.settimeout(.3)
try:
    connection.connect(listener.getsockname())
except OSError:
    pass
else:
    raise AssertionError('worker could access its loopback listener')
finally:
    connection.close()
    listener.close()
udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
udp.bind(('127.0.0.1',0))
udp.settimeout(.3)
sender=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
try:
    sender.sendto(b'direct DNS/QUIC attempt',udp.getsockname())
except OSError:
    # A kernel OUTPUT DROP may reject sendto immediately rather than silently
    # dropping the datagram. Both outcomes enforce the same denial boundary.
    pass
try:
    udp.recvfrom(1024)
except socket.timeout:
    pass
else:
    raise AssertionError('worker escaped through UDP')
finally:
    sender.close()
    udp.close()
with socket.create_connection(('172.29.0.2',8080),timeout=3) as connection:
    connection.sendall(b'GET http://169.254.169.254/latest/meta-data HTTP/1.0\\r\\n\\r\\n')
    assert b'403' in connection.recv(4096)
with socket.create_connection(('172.29.0.2',8080),timeout=3) as connection:
    connection.sendall(b'CONNECT 169.254.169.254:443 HTTP/1.0\\r\\n\\r\\n')
    assert b'403' in connection.recv(4096)
child="import os,pathlib; assert os.getenv('SKRILLER_HOST_ONLY_SECRET') is None; assert 'CapEff:\\t0000000000000000' in pathlib.Path('/proc/self/status').read_text()"
subprocess.run([sys.executable,'-c',child],check=True,timeout=3)
print('kernel and filesystem boundaries verified')
"""
    container = "skriller-boundary-test-" + uuid.uuid4().hex
    command = [
        "/usr/local/bin/docker",
        "run",
        "--rm",
        "--name",
        container,
        "--network",
        "skriller_egress_workers",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "NET_ADMIN",
        "--cap-add",
        "SETUID",
        "--cap-add",
        "SETGID",
        "--cap-add",
        "SETPCAP",
        "--security-opt",
        "no-new-privileges:true",
        "--pids-limit",
        "64",
        "--memory",
        "128m",
        "--env",
        "SKRILLER_PROXY_IP=172.29.0.2",
        "--env",
        "SKRILLER_RUN_UID=65532",
        "--env",
        "SKRILLER_RUN_GID=65532",
        os.environ.get("SKRILLER_EGRESS_TEST_IMAGE", "skriller-egress-worker-test"),
        "python",
        "-c",
        code,
        str(sentinel),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env={**os.environ, "SKRILLER_HOST_ONLY_SECRET": "host-process-sentinel"},
        )
    finally:
        # Client timeout must not leave a daemon-owned test worker alive.
        cleanup = subprocess.run(
            ["/usr/local/bin/docker", "rm", "-f", container],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert cleanup.returncode == 0 or "No such container" in cleanup.stderr, cleanup.stderr
    assert result.returncode == 0, result.stdout + result.stderr
    assert "kernel and filesystem boundaries verified" in result.stdout
