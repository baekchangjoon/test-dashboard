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


def test_req075_bundle_hash_stable_across_checkouts(s02_stage, tmp_path, fake_claude):
    """번들 부분: 같은 SUT 커밋을 서로 다른 체크아웃 경로에서 S02 -> 번들 조립하면 arm별 입력 해시가 같다.
    S03/S05 산출물은 같은 고정 입력을 두 run에 둔다(S03 단독 안정성은 Task 3의 결정적 정렬이 맡는다)."""
    import shutil
    from td import bundle

    runs = [s02_stage(checkout="alpha/checkout-one"), s02_stage(checkout="zz/much/deeper/other-name")]
    ontology = '{"edges": [], "meta": {"commit": "b6f9393"}, "nodes": []}\n'
    for run in runs:
        assert run.stage["status"] == "passed", run.stage
        (run.run_dir / "S03").mkdir(exist_ok=True)
        (run.run_dir / "S03" / "ontology-jqa.json").write_text(ontology)
    assert runs[0].sut_src != runs[1].sut_src
    for arm in ("base", "jqa"):
        hashes = [bundle.assemble(arm, run.run_dir, tmp_path / f"b-{arm}-{index}").input_hash
                  for index, run in enumerate(runs)]
        assert hashes[0] == hashes[1], arm
        # 정제 산출물에 체크아웃 경로가 새지 않는다
        for run in runs:
            for path in (tmp_path / f"b-{arm}-0").rglob("*.json"):
                assert str(run.sut_src) not in path.read_text()
    assert bundle.assemble("base", runs[0].run_dir, tmp_path / "x").input_hash != \
        bundle.assemble("jqa", runs[0].run_dir, tmp_path / "y").input_hash
    assert fake_claude.calls == []
