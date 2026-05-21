"""PointsChain package facade."""

from . import schema as _schema
from .service import PointsLedgerService
from .wallet_facade import WalletFacadeConflict, WalletFacadeInProgress, WalletServiceFacade
from .wallet_identity import (
    address_from_public_key,
    award_signup_bonus_after_wallet_onboarding,
    bind_self_custody_wallet,
    create_multisig_wallet,
    create_official_hot_wallet,
    ensure_system_wallets,
    ensure_wallet_identity_schema,
    serialize_wallet_identity,
    wallet_binding_payload,
    wallet_onboarding_status,
)

globals().update({name: value for name, value in _schema.__dict__.items() if not name.startswith("__")})
