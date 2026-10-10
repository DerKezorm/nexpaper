"""Profile pictures: drawn anew as a small square WebP without anything of the file that came, seen by everybody on the
server (a family knows each other's faces)."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.services import avatars

from .conftest import make_account, sign_in


def person(name: str) -> TestClient:
    client = TestClient(app, base_url="http://testserver", headers={"X-Nexpaper-Client": f"tab-{name:0<8}"})
    sign_in(client, make_account(name))
    return client


def photo(width: int = 600, height: int = 300, *, gps: bool = True, kind: str = "JPEG") -> bytes:
    """Left half red, right half blue; with a place and a device in its Exif, turned by its orientation (6)."""
    image = Image.new("RGB", (width, height), (220, 30, 30))
    image.paste((30, 30, 220), (width // 2, 0, width, height))
    exif = Image.Exif()
    exif[0x0110] = "Pocket Camera 9"  # model
    exif[0x0112] = 6  # orientation: turned
    if gps:
        exif.get_ifd(0x8825)[2] = (52.0, 31.0, 12.0)
    out = io.BytesIO()
    image.save(out, kind, exif=exif.tobytes())
    return out.getvalue()


def me(client: TestClient) -> dict[str, object]:
    return client.get("/api/v1/auth/me").json()


def test_a_picture_comes_back_small_square_upright_and_without_its_metadata(client: TestClient, account: object) -> None:
    anna = person("anna")
    assert me(anna)["avatar"] is None
    answer = anna.put("/api/v1/auth/avatar", content=photo())
    assert answer.status_code == 200
    stamp = answer.json()["avatar"]
    assert stamp and me(anna)["avatar"] == stamp
    own = anna.get(f"/api/v1/avatars/{me(anna)['id']}")
    assert own.status_code == 200 and own.headers["content-type"] == "image/webp"
    assert "private" in own.headers["cache-control"]
    kept = Image.open(io.BytesIO(own.content))
    assert kept.format == "WEBP" and kept.size == (avatars.SIZE, avatars.SIZE)
    assert not kept.getexif() and "xmp" not in kept.info and "exif" not in kept.info
    assert b"Pocket Camera" not in own.content
    # Turned upright (orientation 6: the red left half is on top now) and cut to its middle.
    top = kept.convert("RGB").getpixel((avatars.SIZE // 2, 10))
    low = kept.convert("RGB").getpixel((avatars.SIZE // 2, avatars.SIZE - 10))
    assert top[0] > 150 > top[2] and low[2] > 150 > low[0], (top, low)


def test_only_pictures_come_in(client: TestClient, account: object) -> None:
    anna = person("anna")
    for body in (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", b"<html>hi</html>", b""):
        answer = anna.put("/api/v1/auth/avatar", content=body)
        assert (answer.status_code, answer.json()["detail"]["code"]) == (422, "avatar_not_a_picture")
    # Looks like a JPEG at the start, is not one after.
    broken = anna.put("/api/v1/auth/avatar", content=b"\xff\xd8\xff\xe0" + b"\x00" * 200)
    assert broken.json()["detail"]["code"] == "avatar_not_a_picture"
    # Kinds the decoder would open but no camera makes (TIFF here; EPS would even start Ghostscript): refused first.
    tiff = io.BytesIO()
    Image.new("RGB", (20, 20)).save(tiff, "TIFF")
    assert anna.put("/api/v1/auth/avatar", content=tiff.getvalue()).json()["detail"]["code"] == "avatar_not_a_picture"
    # Tiny on disk, huge in memory.
    huge = io.BytesIO()
    Image.new("1", (8000, 8000)).save(huge, "PNG")
    assert anna.put("/api/v1/auth/avatar", content=huge.getvalue()).json()["detail"]["code"] == "avatar_too_large"
    assert me(anna)["avatar"] is None
    # A PNG and a WebP are pictures too.
    assert anna.put("/api/v1/auth/avatar", content=photo(kind="PNG")).status_code == 200
    assert anna.put("/api/v1/auth/avatar", content=photo(kind="WEBP")).status_code == 200


def test_seen_by_everybody_on_the_server(client: TestClient, account: object) -> None:
    """A family knows each other's faces: every account sees every picture."""
    anna, bob, carl = person("anna"), person("bob"), person("carl")
    assert anna.put("/api/v1/auth/avatar", content=photo()).status_code == 200
    address = f"/api/v1/avatars/{me(anna)['id']}"
    assert client.get(address).status_code == 200  # the operator
    assert bob.get(address).status_code == 200
    # Carl has no picture: 404, as for an account that does not exist.
    assert anna.get(f"/api/v1/avatars/{me(carl)['id']}").status_code == 404
    assert anna.get("/api/v1/avatars/999999").status_code == 404
    # Removed: gone for everyone.
    assert anna.delete("/api/v1/auth/avatar").json()["avatar"] is None
    assert bob.get(address).status_code == 404


@pytest.mark.parametrize("size", [(300, 900), (900, 300)])
def test_a_long_picture_is_cut_to_its_middle_not_squeezed(client: TestClient, account: object, size: tuple[int, int]) -> None:
    """Three bands along its length, green, white, black: the middle one fills the square, corners and all."""
    width, height = size
    image = Image.new("RGB", size, (30, 200, 30))
    third = (width // 3, 0, 2 * width // 3, height) if width > height else (0, height // 3, width, 2 * height // 3)
    image.paste((255, 255, 255), third)
    image.paste((0, 0, 0), (2 * width // 3, 0, width, height) if width > height else (0, 2 * height // 3, width, height))
    out = io.BytesIO()
    image.save(out, "PNG")
    anna = person("anna")
    assert anna.put("/api/v1/auth/avatar", content=out.getvalue()).status_code == 200
    kept = Image.open(io.BytesIO(anna.get(f"/api/v1/avatars/{me(anna)['id']}").content)).convert("RGB")
    assert kept.size == (avatars.SIZE, avatars.SIZE)
    for corner in ((4, 4), (avatars.SIZE - 5, avatars.SIZE - 5)):
        assert min(kept.getpixel(corner)) > 200, kept.getpixel(corner)


def png_claiming(width: int, height: int) -> bytes:
    """Only the head of a PNG: it says how large the picture is, and nothing else follows. A few dozen bytes."""
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    head = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(b"")) + chunk(b"IEND", b"")


def test_a_picture_bomb_is_too_large_not_no_picture(client: TestClient, account: object) -> None:
    anna = person("anna")
    answer = anna.put("/api/v1/auth/avatar", content=png_claiming(20000, 20000))
    assert (answer.status_code, answer.json()["detail"]["code"]) == (422, "avatar_too_large")
    assert answer.json()["detail"]["max_mb"] == avatars.MAX_BYTES // (1024 * 1024)


def test_the_route_and_the_request_guard_hold_the_same_limit(client: TestClient, account: object) -> None:
    from app import middleware

    assert middleware.LARGE_BODIES["/api/v1/auth/avatar"] == avatars.MAX_BYTES
    anna = person("anna")
    # Just above it, said by the guard before anything is read, with the same number.
    answer = anna.put("/api/v1/auth/avatar", content=b"\xff\xd8\xff" + b"\0" * avatars.MAX_BYTES)
    assert answer.status_code == 413
    assert answer.json()["detail"] == {"code": "too_large", "message": "The request is too large.",
                                       "max_mb": avatars.MAX_BYTES // (1024 * 1024)}
