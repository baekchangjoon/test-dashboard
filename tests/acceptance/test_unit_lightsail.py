"""Caddyfile/compose 패치 로직 단위 테스트."""
import pytest

from td import lightsail

CADDYFILE = "# 주석\nsonar.example.test {\n\treverse_proxy sonarqube:9000\n}\n"
BLOCK = "__DASH_ADDR__ {\n\troot * /srv/dashboard\n\tencode gzip\n\tfile_server\n}\n"
COMPOSE = """services:
  caddy:
    image: caddy:2
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
  other:
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
"""
VOLUME = "      - __DASH_DIR__:/srv/dashboard:ro\n"


def test_caddyfile_appends_block_with_address():
    out = lightsail.patch_caddyfile(CADDYFILE, BLOCK, "dash.example.test")
    assert out.startswith(CADDYFILE)
    assert "dash.example.test {\n\troot * /srv/dashboard\n\tencode gzip\n\tfile_server\n}\n" in out


def test_caddyfile_patch_is_idempotent():
    once = lightsail.patch_caddyfile(CADDYFILE, BLOCK, "dash.example.test")
    assert lightsail.patch_caddyfile(once, BLOCK, "dash.example.test") == once


def test_caddyfile_without_trailing_newline_gets_separator():
    out = lightsail.patch_caddyfile("a {\n}", BLOCK, "dash.example.test")
    assert out.startswith("a {\n}\n\ndash.example.test {")


def test_compose_adds_volume_only_to_caddy_service():
    out = lightsail.patch_compose(COMPOSE, VOLUME, "/srv/dashboard")
    caddy_part, other_part = out.split("  other:")
    assert "      - /srv/dashboard:/srv/dashboard:ro\n" in caddy_part
    assert "/srv/dashboard" not in other_part
    assert caddy_part.index("Caddyfile:/etc/caddy") < caddy_part.index("/srv/dashboard:/srv/dashboard:ro") < caddy_part.index("caddy_data")


def test_compose_patch_is_idempotent():
    once = lightsail.patch_compose(COMPOSE, VOLUME, "/srv/dashboard")
    assert lightsail.patch_compose(once, VOLUME, "/srv/dashboard") == once


def test_compose_without_caddy_anchor_raises():
    with pytest.raises(ValueError):
        lightsail.patch_compose("services:\n  web:\n    image: x\n", VOLUME, "/srv/dashboard")


def test_caddyfile_existing_block_is_replaced_when_template_changes():
    old = lightsail.patch_caddyfile(CADDYFILE, BLOCK, "dash.example.test")
    new_block = BLOCK.replace("file_server", "file_server {\n\t\thide .* *.env *.bak\n\t}")
    out = lightsail.patch_caddyfile(old, new_block, "dash.example.test")
    assert "hide .* *.env *.bak" in out
    assert out.count("dash.example.test {") == 1
    assert out.startswith(CADDYFILE)
    assert lightsail.patch_caddyfile(out, new_block, "dash.example.test") == out
