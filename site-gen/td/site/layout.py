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
    # generation마다 하나: 키 `html:<genId>` -> `cucumber/<genId>/`(Cucumber 내장 HTML, REQ-062)
    "S07/html:*": "cucumber/*/",
}

# run 페이지의 링크: 사이트 경로(SITE_LAYOUT 값) -> (표시 이름, 진입 파일)
REPORTS: dict[str, tuple[str, str]] = {
    "ontology/": ("jQA 온톨로지 그래프", "jqa.html"),
    "coverage/": ("커버리지", "coverage.html"),
    "hotspot/": ("hotspot", "hotspots.html"),
    "tia/": ("TIA", "tia.html"),
    "sonar/": ("Sonar 품질 결과", "sonar.html"),
    "cucumber/*/": ("Cucumber 리포트 {}", "index.html"),
}

# 같은 디렉터리의 추가 진입 파일(파일이 있을 때만 링크한다): 사이트 경로 -> [(표시 이름, 진입 파일)]
REPORTS_EXTRA: dict[str, list[tuple[str, str]]] = {
    "ontology/": [("OWL 온톨로지 그래프", "owl.html")],
}
# 주 진입 파일이 없으면 링크하지 않는 디렉터리(S04는 jqa/owl 중 한쪽만 있을 수 있다)
LINK_ONLY_IF_PRESENT = {"ontology/"}

# 게시하지 않는 파일 패턴(.exec는 크고 사이트에서 쓰지 않는다)
COPY_IGNORE = ("*.exec", "exec", "site.css")


def expand_layout(stage_id: str, outputs: dict) -> list[tuple[str, str, str]]:
    """단계 outputs에 맞는 (outputs 키, 사이트 경로, REPORTS 키) 목록. 키 끝이 `*`이면 generation 같은 가변 항목이다
    (`html:*`는 outputs의 `html:<id>` 키마다 사이트 경로의 `*`를 `<id>`로 바꾼다)."""
    entries: list[tuple[str, str, str]] = []
    for key, site_rel in SITE_LAYOUT.items():
        layout_stage, output_key = key.split("/", 1)
        if layout_stage != stage_id:
            continue
        if output_key.endswith("*"):
            prefix = output_key[:-1]
            for actual in sorted(k for k in outputs if k.startswith(prefix) and len(k) > len(prefix)):
                entries.append((actual, site_rel.replace("*", actual[len(prefix):]), site_rel))
        else:
            entries.append((output_key, site_rel, site_rel))
    return entries


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
