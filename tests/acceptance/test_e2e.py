"""E2E 계열 수용 테스트. 이 파일에는 REQ-027(결정적 testId)의 Unit 부분이 있다.
Int 부분(dry-run 두 번의 testId 집합 비교)은 러너를 만드는 Task가 덧붙인다.
"""
import re

import pytest

from td import testid

TEST_ID_RE = re.compile(r"^E2E_(base|jqa|owl)_[0-9a-f]{8}r[1-9](g[0-9]+)?_[A-Za-z0-9_]+#L\d+$")
HASH = "0123456789abcdef" * 4

OUTLINE_FEATURE = """\
Feature: Owner search
  Background:
    Given a thing

  Scenario: plain
    When I search
    Then ok

  @tag
  Scenario Outline: by name <name>
    When I search for "<name>"
    Then I see <count>

    Examples: first
      | name  | count |
      | Davis | 2     |
      | Black | 1     |

    Examples: second
      | name | count |
      | Lee  | 0     |

  Rule: some rule
    Scenario: in rule
      When x
"""


def test_req027_deterministic_testids():
    # Scenario Outline은 Examples 데이터 행마다 하나, L<line>은 그 행의 줄이다. Background와 헤더 행은 시나리오가 아니다.
    picks = testid.pickles(OUTLINE_FEATURE)
    assert [p.line for p in picks] == [5, 16, 17, 21, 24]
    assert picks[1].name == "by name <name>" and picks[0].outline is False and picks[1].outline is True

    def build():
        taken: set[str] = set()
        return [testid.make("jqa", HASH, 2, None, "features/owner.feature", p.line, taken, name="Owner search")
                for p in picks]

    first, second = build(), build()
    assert first == second                      # 같은 입력 -> 같은 집합과 순서
    assert len(set(first)) == len(first)        # 중복 0
    assert all(TEST_ID_RE.match(t) for t in first), first
    assert first[0] == "E2E_jqa_01234567r2_Owner_search#L5"


def test_req027_generation_suffix_and_validation():
    taken: set[str] = set()
    assert testid.make("base", HASH, 1, 2, "a.feature", 3, taken, name="X") == "E2E_base_01234567r1g2_X#L3"
    for bad in [("zzz", HASH, 1, None), ("jqa", HASH, 0, None), ("jqa", HASH, 10, None), ("jqa", "xyz", 1, None)]:
        with pytest.raises(ValueError):
            testid.make(*bad, "a.feature", 3, set())


def test_req027_slug_collision_suffix_per_feature():
    # a/owner.feature {L5, L9}, b/owner.feature {L5, L7}: slug는 feature 단위. b의 모든 id가 owner_2를 쓴다.
    features = {"a/owner.feature": [5, 9], "b/owner.feature": [5, 7], "c/owner.feature": [1]}

    def build():
        slugs: dict[str, str] = {}
        taken: set[str] = set()
        return {path: [testid.make("owl", HASH, 1, None, path, line, taken, slugs=slugs) for line in lines]
                for path, lines in sorted(features.items())}

    ids = build()
    assert ids["a/owner.feature"] == ["E2E_owl_01234567r1_owner#L5", "E2E_owl_01234567r1_owner#L9"]
    assert ids["b/owner.feature"] == ["E2E_owl_01234567r1_owner_2#L5", "E2E_owl_01234567r1_owner_2#L7"]
    assert ids["c/owner.feature"] == ["E2E_owl_01234567r1_owner_3#L1"]
    assert build() == ids
    flat = [t for group in ids.values() for t in group]
    assert len(set(flat)) == len(flat) and all(TEST_ID_RE.match(t) for t in flat)
    # 호출 순서가 아니라 feature가 slug를 소유한다: b를 먼저 말해도 같은 feature 안에서는 일정하다
    slugs: dict[str, str] = {}
    first = testid.make("owl", HASH, 1, None, "b/owner.feature", 5, set(), slugs=slugs)
    again = testid.make("owl", HASH, 1, None, "b/owner.feature", 7, set(), slugs=slugs)
    assert first.split("#")[0] == again.split("#")[0]


def test_req027_duplicate_id_without_registry_is_error():
    taken: set[str] = set()
    testid.make("owl", HASH, 1, None, "a/owner.feature", 5, taken)
    with pytest.raises(ValueError):
        testid.make("owl", HASH, 1, None, "a/owner.feature", 5, taken)


def test_req027_korean_names_use_path_hash():
    # Review Focus 4: 이름이 모두 비ASCII이면 feature 경로의 sha1 앞 8자리로 만든 f<hash>다. 비지 않고 결정적이다.
    slug = testid.feature_slug("features/소유자_조회.feature", "소유자 조회")
    assert re.fullmatch(r"f[0-9a-f]{8}", slug)
    assert slug == testid.feature_slug("features/소유자_조회.feature", "소유자 조회")
    assert slug != testid.feature_slug("features/수의사_조회.feature", "수의사 조회")
    # 혼합 이름은 ASCII 부분만 남는다
    assert testid.feature_slug("f.feature", "Owner 조회 API!") == "Owner_API"
    # 이름이 없으면 파일 이름에서 만든다
    assert testid.feature_slug("features/vet-list.feature", None) == "vet_list"
    taken: set[str] = set()
    made = testid.make("base", HASH, 3, None, "features/소유자.feature", 4, taken, name="소유자 조회")
    assert TEST_ID_RE.match(made) and "_f" in made


def test_req027_nonascii_slug_is_checkout_independent():
    # 해시는 generation 루트 기준 상대 경로만 쓴다: 체크아웃(루트)이 달라도 같고, 절대 경로는 명확한 오류다.
    relative = "features/소유자_조회.feature"
    roots = ["/tmp/checkout-one/gen", "/var/other/deeper/path/gen"]
    slugs = {root: testid.feature_slug(relative, "소유자 조회") for root in roots}
    assert len(set(slugs.values())) == 1
    for root in roots:
        with pytest.raises(ValueError, match="상대 경로"):
            testid.feature_slug(f"{root}/{relative}", "소유자 조회")
        with pytest.raises(ValueError, match="상대 경로"):
            testid.make("base", HASH, 1, None, f"{root}/{relative}", 3, set())
