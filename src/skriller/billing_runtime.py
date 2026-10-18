"""Opt-in billing operator service; credentials come from a private config file."""

import argparse
import json
import os
import stat
import time
from pathlib import Path

import sqlalchemy as sa
import uvicorn
from agent_reach.utils.paths import read_small_text_no_follow
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from skriller.billing.checkout import CheckoutConfiguration
from skriller.billing.runtime import ProviderConfiguration, create_ingress, run_once


class Endpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider: str
    account_id: str | None = None
    live_mode: bool = False
    webhook_secret: SecretStr
    api_key: SecretStr
    api_secret: SecretStr | None = None
    stripe_version: str | None = None

    def configuration(self):
        return ProviderConfiguration(
            self.provider,
            self.account_id,
            self.live_mode,
            self.webhook_secret.get_secret_value().encode(),
            self.api_key.get_secret_value(),
            self.api_secret.get_secret_value() if self.api_secret else None,
            self.stripe_version,
        )


class CheckoutSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    firebase_project_id: str
    return_origin: str

    def configuration(self):
        return CheckoutConfiguration(self.firebase_project_id, self.return_origin)


class Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operator_database_url: SecretStr
    endpoints: list[Endpoint] = Field(min_length=1, max_length=8)
    checkout: CheckoutSettings | None = None


def read_configuration(path):
    """Reuse copied Agent-Reach no-follow bounded file reading; never echo errors."""
    try:
        info = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise ValueError
        content = read_small_text_no_follow(Path(path), max_bytes=32768)
        config = Configuration.model_validate_json(content or "")
        url = sa.engine.make_url(config.operator_database_url.get_secret_value())
        if url.get_backend_name() != "postgresql" or not url.host or not url.database:
            raise ValueError
        endpoints = tuple(endpoint.configuration() for endpoint in config.endpoints)
        if config.checkout:
            config.checkout.configuration()
        if len({(endpoint.provider, endpoint.scope) for endpoint in endpoints}) != len(endpoints):
            raise ValueError
        return config, endpoints
    except Exception:  # noqa: BLE001 - raw validation errors include secret config values
        raise ValueError("A valid private billing configuration is required") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("serve", "worker", "once", "provision"))
    parser.add_argument("--config-file", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8011)
    args = parser.parse_args()
    engine = None
    try:
        config, endpoints = read_configuration(args.config_file)
        engine = sa.create_engine(
            config.operator_database_url.get_secret_value(),
            pool_size=2,
            max_overflow=0,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"connect_timeout": 5},
        )
        if args.mode == "provision":
            from skriller.billing.plans import PLANS
            from skriller.billing.provisioning import provision_plan

            receipts = [
                {
                    "provider": endpoint.provider,
                    "account_scope": endpoint.scope,
                    "plan": slug,
                    **provision_plan(engine, endpoint, slug),
                }
                for endpoint in endpoints
                for slug in PLANS
            ]
            print(json.dumps({"plans": receipts}))
        elif args.mode == "serve":
            uvicorn.run(
                create_ingress(
                    engine,
                    endpoints,
                    checkout=config.checkout.configuration() if config.checkout else None,
                ),
                host=args.host,
                port=args.port,
                access_log=False,
                log_level="warning",
            )
        else:
            while True:
                statuses = run_once(engine, endpoints)
                if args.mode == "once":
                    print(json.dumps({"processed": len(statuses), "statuses": statuses}))
                    return
                time.sleep(10)
    except Exception:  # noqa: BLE001 - no operator URL/provider key in service diagnostics
        parser.exit(2, "Billing service configuration or dependency unavailable\n")
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
