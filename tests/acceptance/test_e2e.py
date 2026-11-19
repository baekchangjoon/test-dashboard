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


def test_req027_slug_collision_suffix_deterministic():
    features = {"b/owner.feature": 5, "a/owner.feature": 5}   # slug가 같고 줄도 같다
    ids = {}
    taken: set[str] = set()
    for path in sorted(features):                               # 상대 경로 순서
        ids[path] = testid.make("owl", HASH, 1, None, path, features[path], taken)
    assert ids == {"a/owner.feature": "E2E_owl_01234567r1_owner#L5", "b/owner.feature": "E2E_owl_01234567r1_owner_2#L5"}
    # 세 번째 충돌은 _3
    assert testid.make("owl", HASH, 1, None, "c/owner.feature", 5, taken) == "E2E_owl_01234567r1_owner_3#L5"
    assert all(TEST_ID_RE.match(t) for t in ids.values())
    # 같은 호출을 다시 해도 같다
    again, taken2 = {}, set()
    for path in sorted(features):
        again[path] = testid.make("owl", HASH, 1, None, path, features[path], taken2)
    assert again == ids


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
