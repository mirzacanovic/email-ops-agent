"""Password hashing with stdlib scrypt -- no extra dependency, and a
memory-hard KDF rather than a fast hash. Stored as
`scrypt$<n>$<r>$<p>$<salt hex>$<hash hex>` so the parameters can be raised
later without invalidating existing hashes.
"""

import hashlib
import hmac
import secrets

_N, _R, _P = 2**14, 8, 1
_KEY_LEN = 32


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=_KEY_LEN)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, _N, _R, _P)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = _scrypt(password, bytes.fromhex(salt_hex), int(n), int(r), int(p))
        return hmac.compare_digest(digest, bytes.fromhex(hash_hex))
    except ValueError:
        return False


# Verified against when the username doesn't exist, so a wrong username and
# a wrong password cost the same time and can't be told apart by timing.
DUMMY_HASH = hash_password(secrets.token_hex(16))
