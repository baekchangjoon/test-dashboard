"""단계 산출물 -> 사이트 경로 매핑(개정 사항 v2 A "사이트 배치").

키는 `<StageID>/<outputs 키>`이고, 단계 JSON의 `outputs[<outputs 키>]`가 가리키는 디렉터리를 run 사이트의
값 경로(끝의 `/`는 디렉터리)로 옮긴다. 여기에 없는 산출물(예: S01 junit, exec)은 게시하지 않는다.
리포트를 추가하는 Task는 이 표와 templates/run.html.j2의 링크 정의(REPORTS)에 항목을 더한다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

SITE_LAYOUT: dict[str, str] = {
    "S04/ontology": "ontology/",
    "S08/coverage": "coverage/",
    "S09/hotspot": "hotspot/",
    "S10/tia": "tia/",
    "S11/sonar": "sonar/",
}

# run 페이지의 링크: 사이트 경로(SITE_LAYOUT 값) -> (표시 이름, 진입 파일)
REPORTS: dict[str, tuple[str, str]] = {
    "ontology/": ("jQA 온톨로지 그래프", "jqa.html"),
    "coverage/": ("커버리지", "coverage.html"),
    "hotspot/": ("hotspot", "hotspots.html"),
    "tia/": ("TIA", "tia.html"),
    "sonar/": ("Sonar 품질 결과", "sonar.html"),
}

# 같은 디렉터리의 추가 진입 파일(파일이 있을 때만 링크한다): 사이트 경로 -> [(표시 이름, 진입 파일)]
REPORTS_EXTRA: dict[str, list[tuple[str, str]]] = {
    "ontology/": [("OWL 온톨로지 그래프", "owl.html")],
}
# 주 진입 파일이 없으면 링크하지 않는 디렉터리(S04는 jqa/owl 중 한쪽만 있을 수 있다)
LINK_ONLY_IF_PRESENT = {"ontology/"}

# 게시하지 않는 파일 패턴(.exec는 크고 사이트에서 쓰지 않는다)
COPY_IGNORE = ("*.exec", "exec", "site.css")


# 복사된 리포트를 사이트 공통 CSS로 다시 만드는 훅: 사이트 경로 -> fn(복사된 디렉터리, css_href)
def _rerender_coverage(target: Path, css_href: str) -> None:
    if (target / "coverage.json").exists():  # 단독 열람용 사본 site.css는 복사에서 뺐다
        from td import coverage
        coverage.render_page(target, json.loads((target / "coverage.json").read_text()), css_href=css_href, copy_css=False)


def _rerender_sonar(target: Path, css_href: str) -> None:
    if (target / "sonar.json").exists():
        from td import sonar
        sonar.render(json.loads((target / "sonar.json").read_text()), target, css_href=css_href, copy_css=False)


RERENDER: dict[str, Callable[[Path, str], None]] = {
    "coverage/": _rerender_coverage,
    "sonar/": _rerender_sonar,
}
