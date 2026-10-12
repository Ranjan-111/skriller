"""Run the enforcing proxy; private-address exceptions do not exist."""

import argparse

from skriller.security.proxy import GuardedProxy

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    with GuardedProxy((args.bind, args.port)) as server:
        server.serve_forever()
