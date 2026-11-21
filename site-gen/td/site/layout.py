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
    "S12/compare": "compare/",
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
    "compare/": ("arm 비교 판정", "compare.html"),
    "cucumber/*/": ("Cucumber 리포트 {}", "index.html"),
}

# 같은 디렉터리의 추가 진입 파일(파일이 있을 때만 링크한다): 사이트 경로 -> [(표시 이름, 진입 파일)]
REPORTS_EXTRA: dict[str, list[tuple[str, str]]] = {
    "ontology/": [("OWL 온톨로지 그래프", "owl.html")],
}
# 주 진입 파일이 없으면 링크하지 않는 디렉터리(S04는 jqa/owl 중 한쪽만 있을 수 있다)
LINK_ONLY_IF_PRESENT = {"ontology/"}

# 리포트 카드의 한 줄 설명(시안 project.html "리포트 바로가기"): 사이트 경로 -> 설명
# 키는 사이트 경로, 또는 같은 디렉터리의 추가 진입 파일이면 그 파일까지(`ontology/owl.html`)
REPORT_NOTES: dict[str, str] = {
    "ontology/": "코드 구조 그래프",
    "ontology/owl.html": "도메인 지식 그래프",
    "coverage/": "테스트별로 지키는 코드",
    "hotspot/": "먼저 손볼 코드",
    "tia/": "변경에 영향받는 테스트",
    "sonar/": "정적 분석 이슈",
    "compare/": "생성 방식 판정",
    "cucumber/*/": "생성 E2E 시나리오 결과",
}

# 공통 띠를 끼워 넣을 외부 도구 HTML(설계 §5.5): 사이트 경로(`*`는 generation) -> 진입 파일들.
# 직접 만드는 리포트(커버리지, Sonar, 방식 비교)는 템플릿이 띠를 그린다(Task 8).
NAV_INJECT: dict[str, list[str]] = {
    "hotspot/": ["hotspots.html", "api_report.html"],
    "tia/": ["tia.html"],
    "cucumber/*/": ["index.html"],
    "ontology/": ["jqa.html", "owl.html"],
}
# 띠의 "지금 리포트" 이름: run 페이지 리포트 목록에 없는 진입 파일만 둔다(사이트 상대 경로 -> 표시 이름)
NAV_EXTRA_LABELS: dict[str, str] = {
    "hotspot/api_report.html": "hotspot API 리포트",
}

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


def _rerender_compare(target: Path, css_href: str) -> None:
    if (target / "compare.json").exists():
        from td import compare
        compare.render_page(target, json.loads((target / "compare.json").read_text()), css_href=css_href, copy_css=False)


RERENDER: dict[str, Callable[[Path, str], None]] = {
    "coverage/": _rerender_coverage,
    "sonar/": _rerender_sonar,
    "compare/": _rerender_compare,
}
