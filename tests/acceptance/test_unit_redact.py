"""td.redact 단위 테스트(I-2, I-3): 작업/임시 경로 치환, 인프라 식별자·ARN 가림, 누출 게이트."""
import json
import tempfile
from pathlib import Path

import pytest

from td import publish, redact
from td.site import pages

FAKE_ENV_VALUES = {"TD_AWS_ACCOUNT_ID": "999988887777", "TD_IAM_USER": "fake-publisher-user",
                   "TD_LIGHTSAIL_IP": "198.51.100.77", "TD_SSH_KEY_PATH": "/opt/keys/fake-lightsail.pem"}


@pytest.fixture
def fake_env(tmp_path):
    root = tmp_path / "root"
    (root / "infra").mkdir(parents=True)
    return {"TD_ROOT": str(root), "TD_WORK_DIR": str(tmp_path / "w" / "work"), **FAKE_ENV_VALUES}


def test_work_and_tmp_paths_are_replaced(tmp_path, fake_env):
    work = Path(fake_env["TD_WORK_DIR"])
    temp = Path(tempfile.gettempdir())
    text = (f"{work}/runs/x {temp}/pytest-of-me/p1/a "
            f"{Path(temp).resolve()}/pytest-of-me/p2/b /private/var/folders/ab/cdef/T/other")
    out = redact.redact_text(text, env=fake_env)
    assert out == "<work>/runs/x <tmp>/pytest-of-me/p1/a <tmp>/pytest-of-me/p2/b <tmp>/other"
    assert redact.find_leaks(out, env=fake_env) == []


def test_identifiers_and_arn_are_masked_from_fake_exception_text(fake_env):
    exc_text = ("AccessDenied: User: arn:aws:iam::999988887777:user/fake-publisher-user is not authorized; "
                "account 999988887777 host 198.51.100.77 key /opt/keys/fake-lightsail.pem")
    out = redact.redact_text(exc_text, env=fake_env)
    for value in FAKE_ENV_VALUES.values():
        assert value not in out
    assert "arn:aws:" not in out and "<arn>" in out and "<redacted>" in out
    assert redact.find_leaks(out, env=fake_env) == []


def test_identifier_match_respects_number_boundaries(fake_env):
    assert redact.redact_text("1198.51.100.778 x9999888877770", env=fake_env) == "1198.51.100.778 x9999888877770"


def test_find_leaks_reports_kinds_without_values(fake_env):
    kinds = redact.find_leaks("at /Users/someone/x and /home/u and arn:aws:s3:::b and 198.51.100.77", env=fake_env)
    assert set(kinds) == {"local-path", "arn", "TD_LIGHTSAIL_IP"}
    assert redact.find_leaks("https://example.com/home/page and ~/x and <tmp>/y", env=fake_env) == []


def test_identifier_values_fall_back_to_local_env(tmp_path):
    root = tmp_path / "r"
    (root / "infra").mkdir(parents=True)
    (root / "infra" / "local.env").write_text("TD_IAM_USER=from-local-env-user\nTD_LIGHTSAIL_IP=\n")
    values = redact.identifier_values({"TD_ROOT": str(root)})
    assert values == {"TD_IAM_USER": "from-local-env-user"}


# --- 사이트 정제기와 게이트(I-2) ------------------------------------------------------------------
def test_sanitize_site_replaces_work_and_tmp_variants(tmp_path, monkeypatch):
    work = tmp_path / "w" / "work"
    monkeypatch.setenv("TD_WORK_DIR", str(work))
    out = tmp_path / "out"
    out.mkdir()
    temp = Path(tempfile.gettempdir()).resolve()
    (out / "manifest.json").write_text(json.dumps({"classesDir": f"{temp}/pytest-of-me/pytest-1/suts/x",
                                                   "w": f"{work}/tools/a.jar"}))
    pages.sanitize_site(out, tmp_path / "run", repo_root=tmp_path / "repo")
    doc = json.loads((out / "manifest.json").read_text())
    assert doc == {"classesDir": "<tmp>/pytest-of-me/pytest-1/suts/x", "w": "<work>/tools/a.jar"}


@pytest.mark.parametrize("leak", ["/Users/someone/p", "/home/someone/p", "/private/var/db/x", "/var/folders/zz/yy/X/q"])
def test_site_gate_rejects_absolute_local_prefixes(tmp_path, leak):
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.json").write_text(json.dumps({"p": leak}))
    with pytest.raises(pages.SanitizeError) as info:
        pages.check_no_home(out)
    assert leak not in str(info.value)


# --- 게시기(I-3) --------------------------------------------------------------------------------
class RecordingS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.read()


def test_write_log_masks_identifiers_arn_and_local_paths(tmp_path, monkeypatch, fake_env):
    for key, value in fake_env.items():
        monkeypatch.setenv(key, value)
    s3 = RecordingS3()
    reason = ("invalidation: ClientError: User: arn:aws:iam::999988887777:user/fake-publisher-user denied; "
              f"ssh 198.51.100.77 -i /opt/keys/fake-lightsail.pem in {tempfile.gettempdir()}/x")
    key = publish.write_log(s3, "b", tmp_path / "mirror", "_test/u/", "sutx", "r1",
                            publish.build_result("degraded", reason, {"cloudfront": {"status": "failed", "reason": reason}}, {}, 0))
    for text in (s3.objects[key].decode(), (tmp_path / "mirror" / key).read_text()):
        for value in FAKE_ENV_VALUES.values():
            assert value not in text
        assert "arn:aws:" not in text and tempfile.gettempdir() not in text


def test_upload_gate_rejects_identifier_in_file(tmp_path, monkeypatch, fake_env):
    for key, value in fake_env.items():
        monkeypatch.setenv(key, value)
    target = tmp_path / "run.json"
    target.write_text(json.dumps({"note": "host 198.51.100.77"}))
    with pytest.raises(publish.PublishError) as info:
        publish.check_no_home_in_file(target, "run.json")
    assert "198.51.100.77" not in str(info.value) and "TD_LIGHTSAIL_IP" in str(info.value)


def test_upload_files_gate_rejects_leaky_index_file(tmp_path, monkeypatch, fake_env):
    for key, value in fake_env.items():
        monkeypatch.setenv(key, value)
    mirror = tmp_path / "mirror"
    (mirror / "_test/u").mkdir(parents=True)
    (mirror / "_test/u/index.html").write_text("<p>arn:aws:iam::1:user/x</p>")
    s3 = RecordingS3()
    with pytest.raises(publish.PublishError):
        publish.upload_files(s3, "b", mirror, [mirror / "_test/u/index.html"])
    assert s3.objects == {}


def test_redact_obj_walks_nested_strings_and_keeps_structure(fake_env):
    doc = {"reason": 'on resource: "arn:aws:s3:::b/k" by 198.51.100.77', "list": ["999988887777", 3, None], "n": 1}
    out = redact.redact_obj(doc, env=fake_env)
    assert out == {"reason": 'on resource: "<arn>" by <redacted>', "list": ["<redacted>", 3, None], "n": 1}
    assert json.loads(json.dumps(out)) == out


def test_arn_inside_json_text_keeps_escapes_valid(fake_env):
    text = json.dumps({"r": 'x "arn:aws:s3:::b/k" y'})
    out = redact.redact_text(text, env=fake_env)
    assert json.loads(out) == {"r": 'x "<arn>" y'}
