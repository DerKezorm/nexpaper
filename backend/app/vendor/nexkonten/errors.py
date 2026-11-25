"""The fixed error codes of the module. The frontend turns a code into a sentence with ``accountErrorKey``
(``konten.ts``), never by showing the code.

``AccountError.message`` is English and meant for an API answer or the log, never for the page. ``status`` is the
HTTP status the module suggests; an app with another error form maps it, the code stays.

An app whose clients know older codes (``name_taken``, ``invalid_email``) keeps them outside: ``AppConfig.error_codes``
maps a module code to the app's, and ``AccountError.public_code`` and ``as_dict()`` answer with it. Inside, and in
the frontend helpers, the module's codes stay.
"""

from __future__ import annotations

#: In a fixed order; the frontend lists them the same way (``ACCOUNT_ERROR_CODES``).
CODES = (
    "setup_code_wrong",
    "already_set_up",
    "display_name_empty",
    "display_name_taken",
    "username_invalid",
    "username_taken",
    "email_invalid",
    "email_taken",
    "email_same",
    "password_too_short",
    "password_too_long",
    "wrong_password",
    "fresh_sign_in_needed",
    "wrong_credentials",
    "account_blocked",
    "not_allowed",
    "not_found",
    "use_account_page",
    "password_login_off",
    "invalid_days",
    "invite_invalid",
    "invite_expired",
    "reset_invalid",
    "reset_expired",
    "email_link_invalid",
    "email_link_expired",
    "no_pending_email",
    # since 0.3.0: second factor, passkeys, sessions, pictures
    "code_wrong",
    "enrolment_expired",
    "sign_in_expired",
    "factor_missing",
    "factor_required",
    "passkeys_off",
    "passkey_invalid",
    "passkey_expired",
    "passkey_exists",
    "too_many_passkeys",
    "too_many_attempts",
    "avatar_too_large",
    "avatar_not_a_picture",
    "avatars_busy",
    "public_url_needed",
)


class AccountError(Exception):
    """A refusal the person or the operator can act on. ``code`` is one of ``CODES``. ``account_id`` names the
    account a refusal was about where the module knows it (a wrong password: the app's brake counts there); it is
    never part of an answer."""

    def __init__(self, code: str, message: str, status: int = 400, **extra: object) -> None:
        if code not in CODES:
            raise ValueError(f"unknown account error code {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra
        self.account_id: object = None

    @property
    def public_code(self) -> str:
        """The code as the app's clients know it (``AppConfig.error_codes``), else the module's."""
        from . import config

        try:
            mapping = config.current().error_codes
        except RuntimeError:
            return self.code
        return mapping.get(self.code, self.code)

    def as_dict(self) -> dict[str, object]:
        return {"code": self.public_code, "message": self.message, **self.extra}


class PictureRefused(Exception):
    """A provider's picture that is not taken; the message says why, for the log (never shown to anybody)."""
