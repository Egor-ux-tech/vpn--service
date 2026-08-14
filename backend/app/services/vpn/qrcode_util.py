import base64
from io import BytesIO

import qrcode


def generate_qr_code_base64(data: str) -> str:
    """Renders a QR code PNG for a WireGuard config and returns it base64-encoded.
    Never called with anything other than a config the caller is about to hand to its
    owner — callers must not persist or log the output."""
    img = qrcode.make(data)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")
