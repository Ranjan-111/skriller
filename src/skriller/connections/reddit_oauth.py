"""Reddit grants reuse the tested encrypted owner-consent lifecycle."""

import sqlalchemy as sa

from skriller.connections.x_oauth import XConsentStore
from skriller.connectors.reddit_oauth import RedditOAuthUnavailable, authorization_url, tokens
from skriller.db.schema import scoped

consents = scoped(
    "reddit_oauth_consents",
    sa.Column("created_by", sa.String(128), nullable=False),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("state_hash", sa.String(64)),
    sa.Column("configuration_hash", sa.String(64), nullable=False),
    sa.Column("connection_id", sa.Uuid(as_uuid=False)),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("key_version", sa.String(64), nullable=False),
    sa.Column("nonce", sa.LargeBinary, nullable=False),
    sa.Column("ciphertext", sa.LargeBinary, nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
)


class RedditConsentStore(XConsentStore):
    table = consents
    source = "reddit"
    unavailable = RedditOAuthUnavailable
    token_values = staticmethod(tokens)
    authorize = staticmethod(authorization_url)
