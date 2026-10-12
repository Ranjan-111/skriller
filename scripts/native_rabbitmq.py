"""Control only the isolated project broker; never installs a global service."""

import os
import secrets
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1] / ".runtime/rabbitmq"
root.mkdir(parents=True, exist_ok=True)
alias = Path("/private/tmp/skriller-native-rabbitmq-runtime")
if alias.is_symlink():
    if alias.resolve() != root:
        raise SystemExit("Runtime alias belongs to another location")
elif alias.exists():
    raise SystemExit("Runtime alias already exists without expected symlink")
else:
    alias.symlink_to(root, target_is_directory=True)
for folder in ("data", "logs"):
    (root / folder).mkdir(exist_ok=True)
cookie = root / ".erlang.cookie"
if not cookie.exists():
    cookie.write_text(secrets.token_urlsafe(32))
cookie.chmod(0o600)
(root / "rabbitmq.conf").write_text(
    "listeners.tcp.1 = 127.0.0.1:56739\ndefault_user = skriller\ndefault_pass = local-development\n"
)
(root / "enabled_plugins").write_text("[].\n")
(root / "isolated-env.conf").write_text(
    "LOG_BASE=/private/tmp/skriller-native-rabbitmq-runtime/logs\n"
)
env = os.environ.copy()
env.update(
    {
        "RABBITMQ_CONF_ENV_FILE": str(alias / "isolated-env.conf"),
        "XDG_CONFIG_HOME": str(alias / "config"),
        "RABBITMQ_NODENAME": "skriller_native@localhost",
        "RABBITMQ_NODE_IP_ADDRESS": "127.0.0.1",
        "RABBITMQ_NODE_PORT": "56739",
        "RABBITMQ_DIST_PORT": "25679",
        "RABBITMQ_CONFIG_FILE": str(alias / "rabbitmq.conf"),
        "RABBITMQ_ENABLED_PLUGINS_FILE": str(alias / "enabled_plugins"),
        "RABBITMQ_MNESIA_DIR": str(alias / "data"),
        "RABBITMQ_LOG_BASE": str(alias / "logs"),
        "RABBITMQ_PID_FILE": str(alias / "broker.pid"),
        "RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS": "-kernel inet_dist_use_interface {127,0,0,1}",
        "RABBITMQ_CTL_ERL_ARGS": "",
        "ERL_EPMD_ADDRESS": "127.0.0.1",
        "ERL_AFLAGS": f"-setcookie {cookie.read_text().strip()}",
        "RABBITMQ_ERLANG_COOKIE": cookie.read_text().strip(),
    }
)
commands = {
    "start": ["/opt/homebrew/opt/rabbitmq/sbin/rabbitmq-server", "-detached"],
    "foreground": ["/opt/homebrew/opt/rabbitmq/sbin/rabbitmq-server"],
    "stop": ["/opt/homebrew/opt/rabbitmq/sbin/rabbitmqctl", "--timeout", "20", "shutdown"],
    "status": ["/opt/homebrew/opt/rabbitmq/sbin/rabbitmq-diagnostics", "--timeout", "20", "ping"],
}
if len(sys.argv) != 2 or sys.argv[1] not in commands:
    raise SystemExit("Usage: control.py start|stop|status")
subprocess.run(commands[sys.argv[1]], env=env, cwd=root, check=True, timeout=30)
