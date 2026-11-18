"""단계 산출물 -> 사이트 경로 매핑(개정 사항 v2 A "사이트 배치").

키는 `<StageID>/<outputs 키>`이고, 단계 JSON의 `outputs[<outputs 키>]`가 가리키는 디렉터리를 run 사이트의
값 경로(끝의 `/`는 디렉터리)로 옮긴다. 여기에 없는 산출물(예: S01 junit, exec)은 게시하지 않는다.
리포트를 추가하는 Task는 이 표와 templates/run.html.j2의 링크 정의(REPORTS)에 항목을 더한다.
"""
from __future__ import annotations

SITE_LAYOUT: dict[str, str] = {
    "S08/coverage": "coverage/",
}

# run 페이지의 링크: 사이트 경로(SITE_LAYOUT 값) -> (표시 이름, 진입 파일)
REPORTS: dict[str, tuple[str, str]] = {
    "coverage/": ("커버리지", "coverage.html"),
}

# 게시하지 않는 파일 패턴(.exec는 크고 사이트에서 쓰지 않는다)
COPY_IGNORE = ("*.exec", "exec", "site.css")
