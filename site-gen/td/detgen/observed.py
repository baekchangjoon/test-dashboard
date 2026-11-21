"""det 시나리오의 관측 상태 코드 복원(Task 8 결과 집계용).

DetSteps는 상태 단정의 AssertJ 설명에 `DET-STATUS <caseId> <code>`를 넣는다. 표준 출력은 보관 로그에 남지 않으므로
실패한 시나리오의 관측 코드는 Cucumber JSON 보고서(cucumber.json)의 step `error_message`에서 읽는다.
시나리오의 케이스 id는 `@case:<id>` 태그에서, 없으면 첫 step 텍스트 `the case "<id>"`에서 얻는다.
통과한 시나리오(메시지 없음)는 None이다. 통과는 관측 코드가 strict 기대를 만족했다는 뜻이다.
"""
from __future__ import annotations

import json
import re

__all__ = ["observed_codes"]

_STATUS = re.compile(r"DET-STATUS (\S+) (\d{3})\b")
_CASE_TAG = "@case:"
_CASE_STEP = re.compile(r'^the case "([^"]+)"$')


def _case_id(element: dict) -> str | None:
    for tag in element.get("tags", []):
        name = tag.get("name", "")
        if name.startswith(_CASE_TAG):
            return name[len(_CASE_TAG):]
    steps = element.get("steps", [])
    if steps:
        match = _CASE_STEP.match(steps[0].get("name", ""))
        if match:
            return match.group(1)
    return None


def observed_codes(cucumber_json_text: str) -> dict[str, int | None]:
    """케이스 id → 관측 상태 코드. 실패 메시지에서 찾지 못하면 None이다(통과, 선행 요청 단계 실패 등).
    메시지의 케이스 id가 시나리오의 id와 다르면 쓰지 않는다."""
    result: dict[str, int | None] = {}
    for feature in json.loads(cucumber_json_text):
        for element in feature.get("elements", []):
            if element.get("type") == "background":
                continue
            case_id = _case_id(element)
            if case_id is None:
                continue
            code = None
            for step in element.get("steps", []):
                message = (step.get("result") or {}).get("error_message") or ""
                for match in _STATUS.finditer(message):
                    if match.group(1) == case_id:
                        code = int(match.group(2))
                        break
                if code is not None:
                    break
            result[case_id] = code
    return result
