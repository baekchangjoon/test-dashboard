"""BDD 생성 입력 계열 수용 테스트. 이 파일에는 REQ-075(입력 해시 안정성)의 S02 부분이 있다.
S03(jQA)과 번들 조립 부분, REQ-023/024/025/061은 소유 Task가 이 파일에 덧붙인다.
"""
import hashlib
from pathlib import Path


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def test_req075_input_hash_stable(s02_stage, fake_claude):
    """S02 부분: 같은 SUT 커밋을 서로 다른 체크아웃 경로에 두고 두 번 돌리면 clean/의 sha256이 같다."""
    first = s02_stage(checkout="alpha/checkout-one")
    second = s02_stage(checkout="zz/much/deeper/other-name")
    assert first.stage["status"] == second.stage["status"] == "passed"
    assert first.sut_src != second.sut_src and len(str(first.sut_src)) != len(str(second.sut_src))
    first_hash, second_hash = _tree_sha256(first.clean_dir), _tree_sha256(second.clean_dir)
    assert first_hash == second_hash
    # 정제 결과 요약(제거 필드와 개수)도 같다
    assert first.manifest["sanitize"] == second.manifest["sanitize"]
    assert fake_claude.calls == []
