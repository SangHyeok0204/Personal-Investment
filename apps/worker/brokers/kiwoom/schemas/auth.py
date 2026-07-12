"""Access-token response schema (POST /oauth2/token).

Fields per kiwoom-api-reference.md §2.1 (CONFIRMED: token/token_type/expires_dt/
return_code/return_msg). extra="allow" so any additional fields are preserved.
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    token: Optional[str] = None
    token_type: Optional[str] = None
    # Absolute expiry "YYYYMMDDHHMMSS" in KST (NOT a relative seconds value).
    expires_dt: Optional[str] = None
    return_code: Optional[int] = None
    return_msg: Optional[str] = None
