/* 온톨로지 그래프 화면. 데이터는 DOM 텍스트(textContent)로만 그리고 innerHTML에 넣지 않는다. */
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("td-data").textContent);
  var KINDS = ["Endpoint", "Controller", "Service", "Repository", "Entity", "Field", "Exception", "DTO"];

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
  }
  function el(tag, text, className) {
    var node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }

  // 간선은 양 끝 노드가 모두 있는 것만 쓴다(끝점이 없으면 Cytoscape가 예외를 던진다).
  var ids = {};
  data.nodes.forEach(function (n) { ids[n.id] = true; });
  var elements = data.nodes.map(function (n) {
    return { group: "nodes", data: { id: n.id, label: n.label, kind: n.kind, props: n.props } };
  });
  var skipped = 0;
  data.edges.forEach(function (e, index) {
    if (!ids[e.source] || !ids[e.target]) { skipped += 1; return; }
    elements.push({ group: "edges", data: { id: "e" + index, source: e.source, target: e.target, kind: e.kind } });
  });

  var cy = cytoscape({ elements: elements, headless: false, container: document.getElementById("cy"), wheelSensitivity: 0.3 });
  window.__td_cy = cy;

  function applyTheme() {
    var style = [
      { selector: "node", style: {
          "background-color": function (n) { return cssVar("--k-" + n.data("kind")); },
          label: "data(label)", color: cssVar("--fg"), "font-size": 9, "text-valign": "bottom", "text-margin-y": 3,
          "text-wrap": "ellipsis", "text-max-width": 90, "min-zoomed-font-size": 7, width: 16, height: 16 } },
      { selector: "node[kind = 'Endpoint']", style: { shape: "round-rectangle", width: 22, height: 16 } },
      { selector: "edge", style: {
          width: 1, "line-color": cssVar("--edge"), "target-arrow-color": cssVar("--edge"),
          "target-arrow-shape": "triangle", "curve-style": "bezier", "arrow-scale": 0.7 } },
      { selector: "node.match", style: { "border-width": 3, "border-color": cssVar("--match") } },
      { selector: "node:selected", style: { "border-width": 3, "border-color": cssVar("--accent") } },
      { selector: ".kind-off, .out-sub", style: { display: "none" } }
    ];
    cy.style(style);
  }
  applyTheme();
  var scheme = window.matchMedia("(prefers-color-scheme: dark)");
  if (scheme.addEventListener) scheme.addEventListener("change", applyTheme);

  function relayout() {
    var visible = cy.elements().not(".kind-off, .out-sub");
    if (visible.length === 0) return;
    visible.layout({ name: "cose", animate: false, fit: true, padding: 24, randomize: true, nodeDimensionsIncludeLabels: false }).run();
  }

  // --- 범례와 kind 필터 ---
  var legend = document.getElementById("legend");
  var counts = {};
  data.nodes.forEach(function (n) { counts[n.kind] = (counts[n.kind] || 0) + 1; });
  KINDS.filter(function (k) { return counts[k]; }).forEach(function (kind) {
    var item = el("li");
    var label = el("label");
    var box = el("input");
    box.type = "checkbox"; box.checked = true; box.setAttribute("data-kind", kind);
    var swatch = el("span", "", "swatch");
    swatch.style.setProperty("--c", "var(--k-" + kind + ")");
    label.appendChild(box); label.appendChild(swatch); label.appendChild(document.createTextNode(kind + " (" + counts[kind] + ")"));
    item.appendChild(label); legend.appendChild(item);
    box.addEventListener("change", function () {
      cy.nodes("[kind = '" + kind + "']").toggleClass("kind-off", !box.checked);
      relayout();
    });
  });

  // --- 속성 패널 ---
  var panel = document.getElementById("panel");
  function selectNode(node) {
    cy.elements().unselect();
    node.select();
    renderPanel(node);
  }
  function renderPanel(node) {
    panel.textContent = "";
    var kind = node.data("kind");
    var chip = el("span", kind, "kind-chip");
    chip.style.setProperty("--c", "var(--k-" + kind + ")");
    panel.appendChild(chip);
    panel.appendChild(el("h2", node.data("label")));
    var list = el("dl");
    list.appendChild(el("dt", "id")); list.appendChild(el("dd", node.id()));
    var props = node.data("props") || {};
    Object.keys(props).forEach(function (key) {
      var value = props[key];
      list.appendChild(el("dt", key));
      list.appendChild(el("dd", typeof value === "string" ? value : JSON.stringify(value, null, 2)));
    });
    panel.appendChild(list);
    var neighbors = node.neighborhood("node");
    if (neighbors.length) {
      panel.appendChild(el("h3", "연결된 노드 (" + neighbors.length + ")"));
      var ul = el("ul");
      neighbors.forEach(function (other) {
        var li = el("li");
        var button = el("button", other.data("label") + " [" + other.data("kind") + "]");
        button.type = "button";
        button.addEventListener("click", function () { selectNode(other); cy.animate({ center: { eles: other }, duration: 150 }); });
        li.appendChild(button); ul.appendChild(li);
      });
      panel.appendChild(ul);
    }
    if (kind === "Endpoint") {
      var only = el("button", "이 엔드포인트만 보기");
      only.type = "button";
      only.addEventListener("click", function () { showEndpoint(node.id()); });
      panel.appendChild(only);
    }
  }
  cy.on("tap", "node", function (event) { selectNode(event.target); });
  window.__td_select = function (id) { selectNode(cy.getElementById(id)); };

  // --- 검색 ---
  var searchBox = document.getElementById("search");
  var searchCount = document.getElementById("search-count");
  searchBox.addEventListener("input", function () {
    var term = searchBox.value.trim().toLowerCase();
    cy.nodes().removeClass("match");
    if (!term) { searchCount.textContent = ""; return; }
    var hits = cy.nodes().filter(function (n) {
      return (n.data("label") + " " + n.id()).toLowerCase().indexOf(term) !== -1;
    });
    hits.addClass("match");
    searchCount.textContent = "일치 " + hits.length + "개";
    var shown = hits.not(".kind-off, .out-sub");
    if (shown.length === 1) { cy.animate({ center: { eles: shown }, zoom: Math.max(cy.zoom(), 1.2), duration: 150 }); }
    else if (shown.length > 1) { cy.animate({ fit: { eles: shown, padding: 40 }, duration: 150 }); }
  });

  // --- 엔드포인트 하위 그래프: 선택한 엔드포인트와 거기서 간선을 따라 닿는 노드(+ 그 엔드포인트를 가리키는 노드) ---
  var select = document.getElementById("endpoint-select");
  cy.nodes("[kind = 'Endpoint']").sort(function (a, b) { return a.data("label").localeCompare(b.data("label")); })
    .forEach(function (node) {
      var option = el("option", node.data("label"));
      option.value = node.id();
      select.appendChild(option);
    });
  function showEndpoint(id) {
    var endpoint = cy.getElementById(id);
    if (!endpoint.length) return;
    var keep = endpoint.union(endpoint.successors()).union(endpoint.incomers());
    cy.elements().addClass("out-sub");
    keep.removeClass("out-sub");
    select.value = id;
    relayout();
    selectNode(endpoint);
  }
  function resetView() {
    cy.elements().removeClass("out-sub");
    select.value = "";
    relayout();
  }
  select.addEventListener("change", function () { if (select.value) showEndpoint(select.value); else resetView(); });
  document.getElementById("reset-view").addEventListener("click", resetView);

  relayout();
  if (skipped) {
    var note = el("p", "끝점이 없는 간선 " + skipped + "개는 그리지 않았다.", "muted");
    document.getElementById("viz").insertAdjacentElement("beforebegin", note);
  }
  window.__td_ready = true;
})();
