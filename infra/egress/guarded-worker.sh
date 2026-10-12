#!/bin/sh
set -eu
: "${SKRILLER_PROXY_IP:?Explicit reviewed proxy IP required}"
: "${SKRILLER_RUN_UID:?Explicit unprivileged worker UID required}"
: "${SKRILLER_RUN_GID:?Explicit unprivileged worker GID required}"
[ "$SKRILLER_PROXY_IP" = "172.29.0.2" ]
[ "$SKRILLER_RUN_UID" -gt 0 ]
[ "$SKRILLER_RUN_GID" -gt 0 ]
# Applies to every worker socket, including browser subresources and attempts
# to ignore HTTP_PROXY. No worker DNS/UDP/QUIC/WebRTC/direct-private route.
iptables -P OUTPUT DROP
iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -A OUTPUT -p tcp -d "$SKRILLER_PROXY_IP" --dport 8080 -j ACCEPT
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
ip6tables -P OUTPUT DROP
ip6tables -P INPUT DROP
ip6tables -P FORWARD DROP
exec setpriv --reuid="$SKRILLER_RUN_UID" --regid="$SKRILLER_RUN_GID" \
  --clear-groups --bounding-set=-all --inh-caps=-all --ambient-caps=-all \
  --no-new-privs "$@"
