"""PointsChain package facade."""

from . import schema as _schema
from .service import PointsLedgerService
from .wallet_facade import WalletFacadeConflict, WalletFacadeInProgress, WalletServiceFacade
from .wallet_identity import (
    address_dispute_payload,
    address_from_public_key,
    award_signup_bonus_after_wallet_onboarding,
    bind_self_custody_wallet,
    BURN_WALLET_ADDRESS,
    COLD_WALLET_ADDRESS_RE,
    create_multisig_wallet,
    create_official_hot_wallet,
    delete_cold_wallet,
    delete_primary_cold_wallet,
    ensure_system_wallets,
    ensure_wallet_identity_schema,
    has_pc0_prefix,
    INTERNAL_WALLET_ADDRESS_RE,
    is_burn_wallet_address,
    is_pc0_internal_address,
    is_pc1_chain_address,
    is_system_special_address,
    list_wallet_identities,
    MINT_WALLET_ADDRESS,
    normalize_points_chain_address,
    POINTS_CHAIN_ADDRESS_RE,
    serialize_wallet_identity,
    system_account_wallet_onboarding_status,
    SYSTEM_WALLET_ADDRESS_RE,
    wallet_binding_payload,
    wallet_service_fee_payload,
    wallet_transaction_payload,
    verify_wallet_address_dispute_signature,
    verify_wallet_service_fee_signature,
    verify_wallet_transaction_signature,
    wallet_onboarding_status,
)

globals().update({name: value for name, value in _schema.__dict__.items() if not name.startswith("__")})
