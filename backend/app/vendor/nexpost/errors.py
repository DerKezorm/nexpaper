"""The fixed error codes of system mail. The page shows ``mail.error.<code>``; ``MailError.message`` is English, for an
answer or the log (never with an address in it). ``detail`` is the sentence of the mail server where it gave one.
An app whose clients know other codes maps them (``AppConfig.error_codes``)."""

from __future__ import annotations

CODES = (
    "mail_off",
    "mail_unreachable",
    "mail_tls_failed",
    "mail_auth_refused",
    "mail_sender_refused",
    "mail_recipient_refused",
    "mail_refused",
    "mail_failed",
    "mail_address_invalid",
    "mail_settings_invalid",
)

#: Mails that will not go through on another try: given up at once, unless the server said "later" (a 4xx reply:
#: greylisting 450, 451, a temporary failure of the login 454).
FINAL = ("mail_recipient_refused", "mail_address_invalid", "mail_sender_refused", "mail_auth_refused")


def is_final(error: MailError) -> bool:
    """Whether another try cannot help."""
    return error.code in FINAL and not 400 <= error.smtp_code < 500


class MailError(Exception):
    def __init__(
        self, code: str, message: str, *, detail: str = "", status: int = 502, smtp_code: int = 0
    ) -> None:
        if code not in CODES:
            raise ValueError(f"unknown mail error code {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail
        #: The mail server's reply code where it gave one (``450``, ``550``); 0 otherwise.
        self.smtp_code = smtp_code
        self.status = (
            409
            if code == "mail_off"
            else (422 if code in ("mail_address_invalid", "mail_settings_invalid") else status)
        )

    @property
    def public_code(self) -> str:
        from . import config

        try:
            return config.current().error_codes.get(self.code, self.code)
        except RuntimeError:
            return self.code

    def as_dict(self) -> dict[str, object]:
        answer: dict[str, object] = {"code": self.public_code, "message": self.message}
        if self.detail:
            answer["detail"] = self.detail
        return answer
