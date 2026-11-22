/* det 조합 시각화 화면. 데이터 문자열은 DOM 텍스트(textContent)로만 넣는다(HTML 문자열 삽입 API를 쓰지 않는다). */
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("td-data").textContent);
  var factors = data.factors;
  var results = data.caseResults || {};
  var aggregates = data.aggregates;
  var trace = data.trace || { caseSources: {}, unresolvedEndpoints: [] };
  var sources = factors.sources || {};

  // 상태 → [기호, 설명]. 색은 CSS 클래스 st-<state>가 정한다.
  var STATES = {
    "covered-pass": ["✓", "통과 케이스가 덮음"],
    "covered-fail": ["✗", "실패 케이스만 덮음"],
    "covered-notrun": ["○", "실행 안 된 케이스만 덮음"],
    "unresolved": ["⊘", "생성 불가 슬롯만 있음"],
    "empty": ["·", "비어 있음"]
  };
  var CASE_STATE = { passed: "covered-pass", failed: "covered-fail", notRun: "covered-notrun" };
  var CASE_TEXT = { passed: "통과", failed: "실패", notRun: "실행 안 됨" };

  function el(tag, text, className) {
    var node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }
  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }
  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
  }
  function stripTilde(address) {
    return String(address).replace(/~+$/, "");
  }
  function shortField(field) {
    var index = field.indexOf(".");
    return index >= 0 ? field.slice(index + 1) : field;
  }
  function conditionOf(address) {
    var entry = sources[address];
    return entry && entry.condition ? entry.condition : null;
  }
  function symbol(state) {
    var span = el("span", (STATES[state] || ["?"])[0], "sym st-" + state);
    span.title = (STATES[state] || ["", state])[1];
    return span;
  }

  // --- 색인 ---
  var classInfo = {};      // 클래스 id → {endpoint, field, klass}
  var endpointOrder = [];
  factors.endpoints.forEach(function (entry) {
    endpointOrder.push(entry.endpoint);
    entry.fields.forEach(function (field) {
      field.classes.forEach(function (klass) {
        classInfo[klass.id] = { endpoint: entry.endpoint, field: field.field, klass: klass };
      });
    });
  });
  function classAggregate(classId) {
    var info = classInfo[classId];
    var byEndpoint = info ? aggregates.byEndpoint[info.endpoint] : null;
    return byEndpoint && byEndpoint.classes[classId] ? byEndpoint.classes[classId] : null;
  }
  function classLabel(classId) {
    var info = classInfo[classId];
    return info ? shortField(info.field) + ": " + info.klass.label : classId;
  }
  function slotEndpoint(position) {
    var endpoint = (trace.unresolvedEndpoints || [])[position];
    if (typeof endpoint === "string") return endpoint;
    var cells = factors.unresolved[position].cells || {};
    for (var field in cells) {
      if (Object.prototype.hasOwnProperty.call(cells, field) && classInfo[cells[field]]) return classInfo[cells[field]].endpoint;
    }
    return null;
  }

  // --- 1. 요약 띠 ---
  (function renderSummary() {
    var summary = aggregates.summary;
    var box = document.getElementById("det-summary");
    var outTotal = 0;
    var outParts = [];
    Object.keys(summary.outOfModel).sort().forEach(function (rule) {
      outTotal += summary.outOfModel[rule];
      outParts.push(rule + " " + summary.outOfModel[rule]);
    });
    [["엔드포인트", summary.endpoints, ""], ["필드", summary.fields, ""], ["클래스(valid 포함)", summary.classes, ""],
     ["덮인 클래스", summary.classesCovered, "/ " + summary.classes],
     ["2-way 쌍", summary.pairsCovered, "/ " + summary.pairsTotal],
     ["모델 밖 케이스", outTotal, outParts.join(", ")]].forEach(function (item) {
      var card = el("div", null, "card");
      card.setAttribute("data-summary", item[0]);
      card.appendChild(el("span", item[0], "muted"));
      card.appendChild(el("b", item[1]));
      if (item[2]) card.appendChild(el("span", item[2], "muted"));
      box.appendChild(card);
    });
    var legend = document.getElementById("det-legend");
    Object.keys(STATES).forEach(function (state) {
      var item = el("li");
      item.appendChild(symbol(state));
      item.appendChild(document.createTextNode(" " + state + " (" + STATES[state][1] + ")"));
      legend.appendChild(item);
    });
  })();

  // --- 상세 패널 ---
  var panel = document.getElementById("panel");
  function panelRows(title, rows) {
    clear(panel);
    panel.appendChild(el("h3", title));
    var list = el("dl");
    rows.forEach(function (row) {
      list.appendChild(el("dt", row[1]));
      var value = el("dd", row[2] === null || row[2] === undefined || row[2] === "" ? "-" : row[2]);
      value.setAttribute("data-k", row[0]);
      list.appendChild(value);
    });
    panel.appendChild(list);
  }
  function showCase(caseId) {
    var result = results[caseId] || {};
    var entry = (factors.cases || {})[caseId] || {};
    var addresses = (trace.caseSources || {})[caseId] || [];
    var conditions = addresses.map(conditionOf).filter(function (text) { return text; });
    var cells = Object.keys(entry.cells || {}).sort().map(function (field) { return field + " = " + classLabel(entry.cells[field]); });
    panelRows("케이스 " + caseId, [
      ["endpoint", "엔드포인트", result.endpoint],
      ["rule", "규칙", entry.rule],
      ["status", "상태", CASE_TEXT[result.status] || result.status],
      ["expect", "기대", result.expectStrict === null || result.expectStrict === undefined ? "-" : String(result.expectStrict)],
      ["observed", "관측", result.observed === null || result.observed === undefined ? "-" : String(result.observed)],
      ["condition", "조건식", conditions.join("\n")],
      ["sources", "출처", addresses.join("\n")],
      ["cells", "값(칸)", cells.join("\n")],
      ["boundaries", "경계", (entry.boundaries || []).map(classLabel).join("\n")],
      ["model", "모델", entry.inModel === false ? "모델 밖(" + entry.outReason + ")" : "모델 안"]
    ]);
  }
  function showClass(classId) {
    var info = classInfo[classId];
    var agg = classAggregate(classId) || {};
    var addresses = info.klass.sources.map(stripTilde);
    panelRows("클래스 " + info.klass.label, [
      ["field", "필드", info.field],
      ["label", "클래스", info.klass.label],
      ["kind", "종류", info.klass.kind],
      ["state", "상태", (STATES[agg.state] || ["?"])[0] + " " + agg.state],
      ["cases", "케이스", (agg.cases || []).join(", ")],
      ["boundaryCases", "경계 케이스 수", String(agg.boundaryCases || 0)],
      ["unresolved", "생성 불가", (agg.unresolved || []).map(function (u) { return "#" + u.index + " " + u.reason; }).join("\n")],
      ["condition", "조건식", addresses.map(conditionOf).filter(function (t) { return t; }).join("\n")],
      ["sources", "출처", addresses.join("\n")]
    ]);
  }
  function showSource(address) {
    var entry = sources[address] || {};
    panelRows("출처", [
      ["address", "주소", address],
      ["kind", "종류", entry.kind],
      ["methods", "메서드", (entry.methods || []).join("\n")],
      ["condition", "조건식", entry.condition],
      ["expected", "기대", entry.expected]
    ]);
  }
  function showSlot(position) {
    var slot = factors.unresolved[position];
    var cells = Object.keys(slot.cells || {}).sort().map(function (field) { return field + " = " + classLabel(slot.cells[field]); });
    panelRows("생성 불가 #" + slot.index, [
      ["endpoint", "엔드포인트", slotEndpoint(position)],
      ["rule", "규칙", slot.rule],
      ["reason", "사유", slot.reason],
      ["condition", "조건식", conditionOf(slot.source)],
      ["sources", "출처", slot.source],
      ["cells", "칸", cells.join("\n")]
    ]);
  }

  // --- 2. 추적 그래프 ---
  var select = document.getElementById("endpoint-select");
  endpointOrder.forEach(function (label) {
    var option = el("option", label);
    option.value = label;
    select.appendChild(option);
  });
  var meta = document.getElementById("graph-meta");
  var cy = cytoscape({ container: document.getElementById("cy"), elements: [], wheelSensitivity: 0.3 });
  window.__td_cy = cy;

  function graphElements(endpoint) {
    var entry = factors.endpoints.filter(function (item) { return item.endpoint === endpoint; })[0];
    var nodes = [];
    var edges = [];
    var seen = {};
    var columns = [[], [], [], []];   // 출처, 클래스, 케이스, 생성 불가
    function addNode(id, column, payload) {
      if (seen[id]) return;
      seen[id] = true;
      payload.id = id;
      columns[column].push({ group: "nodes", data: payload });
    }
    function addEdge(source, target, kind) {
      if (!seen[source] || !seen[target]) return;
      edges.push({ group: "edges", data: { id: "e" + edges.length, source: source, target: target, kind: kind } });
    }
    (entry ? entry.fields : []).forEach(function (field) {
      field.classes.forEach(function (klass) {
        var agg = classAggregate(klass.id) || {};
        addNode(klass.id, 1, { label: classLabel(klass.id), type: "class", ref: klass.id, state: agg.state || "empty" });
        klass.sources.forEach(function (address) {
          var stripped = stripTilde(address);
          addNode("src:" + stripped, 0, { label: conditionOf(stripped) || stripped, type: "source", ref: stripped, state: "source" });
          addEdge("src:" + stripped, klass.id, "source");
        });
      });
    });
    Object.keys(results).sort().forEach(function (caseId) {
      if (results[caseId].endpoint !== endpoint) return;
      addNode("case:" + caseId, 2, { label: caseId, type: "case", ref: caseId, state: CASE_STATE[results[caseId].status] || "covered-notrun" });
      var entryCase = (factors.cases || {})[caseId] || {};
      Object.keys(entryCase.cells || {}).forEach(function (field) { addEdge(entryCase.cells[field], "case:" + caseId, "cell"); });
      (entryCase.boundaries || []).forEach(function (classId) { addEdge(classId, "case:" + caseId, "boundary"); });
    });
    factors.unresolved.forEach(function (slot, position) {
      if (slotEndpoint(position) !== endpoint) return;
      addNode("slot:" + slot.index, 3, { label: "#" + slot.index + " " + slot.reason, type: "slot", ref: String(position), state: "unresolved" });
      Object.keys(slot.cells || {}).forEach(function (field) { addEdge(slot.cells[field], "slot:" + slot.index, "slot"); });
    });
    columns.forEach(function (column, x) {
      column.forEach(function (node, y) {
        node.position = { x: x * 240, y: y * 34 };
        nodes.push(node);
      });
    });
    return { nodes: nodes, edges: edges };
  }

  function applyTheme() {
    var stateColor = {
      "covered-pass": cssVar("--st-pass"), "covered-fail": cssVar("--st-fail"), "covered-notrun": cssVar("--st-notrun"),
      "unresolved": cssVar("--st-unres"), "empty": cssVar("--st-empty"), "source": cssVar("--src")
    };
    cy.style([
      { selector: "node", style: {
          "background-color": function (node) { return stateColor[node.data("state")] || cssVar("--muted"); },
          label: "data(label)", color: cssVar("--fg"), "font-size": 9, "text-valign": "center", "text-halign": "right",
          "text-margin-x": 4, "text-wrap": "ellipsis", "text-max-width": 190, "min-zoomed-font-size": 6, width: 12, height: 12 } },
      { selector: "node[type = 'source']", style: { shape: "round-rectangle", width: 14, height: 10 } },
      { selector: "node[type = 'case']", style: { shape: "diamond" } },
      { selector: "node[type = 'slot']", style: { "background-opacity": 0.15, "border-width": 2, "border-style": "dashed",
          "border-color": stateColor.unresolved } },
      { selector: "edge", style: { width: 1, "line-color": cssVar("--edge"), "target-arrow-color": cssVar("--edge"),
          "target-arrow-shape": "triangle", "curve-style": "bezier", "arrow-scale": 0.6 } },
      { selector: "edge[kind = 'boundary'], edge[kind = 'slot']", style: { "line-style": "dashed" } },
      { selector: "node:selected", style: { "border-width": 3, "border-color": cssVar("--accent") } }
    ]);
  }

  var current = null;
  function showEndpoint(endpoint) {
    current = endpoint;
    if (select.value !== endpoint) select.value = endpoint;
    var built = graphElements(endpoint);
    cy.elements().remove();
    cy.add(built.nodes.concat(built.edges));
    cy.layout({ name: "preset", fit: true, padding: 20 }).run();
    var ids = built.nodes.map(function (node) { return node.data.id; }).sort();
    meta.setAttribute("data-node-count", String(ids.length));
    meta.setAttribute("data-node-ids", ids.join(","));
    meta.textContent = endpoint + " · 노드 " + ids.length + "개 · 간선 " + built.edges.length + "개";
  }

  function selectGraphNode(nodeId) {
    cy.elements().unselect();
    var node = cy.getElementById(nodeId);
    if (node && node.length) {
      node.select();
      cy.center(node);
    }
  }

  // 노드 선택과 같은 동작: 케이스 id·클래스 id·그래프 노드 id(src:·case:·slot:)를 받는다.
  function selectItem(id) {
    id = String(id);
    var prefixed = /^(src|case|slot):/.exec(id);
    var kind = prefixed ? prefixed[1] : null;
    var ref = prefixed ? id.slice(prefixed[0].length) : id;
    if (!kind) {
      if (Object.prototype.hasOwnProperty.call(results, id)) kind = "case";
      else if (classInfo[id]) kind = "class";
      else if (Object.prototype.hasOwnProperty.call(sources, id)) kind = "src";
      else return false;
    }
    var endpoint = null;
    var nodeId = id;
    if (kind === "case") {
      endpoint = (results[ref] || {}).endpoint;
      nodeId = "case:" + ref;
      showCase(ref);
    } else if (kind === "class") {
      endpoint = classInfo[ref].endpoint;
      nodeId = ref;
      showClass(ref);
    } else if (kind === "slot") {
      var position = -1;
      factors.unresolved.forEach(function (slot, i) { if (String(slot.index) === ref) position = i; });
      if (position < 0) return false;
      endpoint = slotEndpoint(position);
      nodeId = "slot:" + ref;
      showSlot(position);
    } else {
      nodeId = "src:" + ref;
      showSource(ref);
    }
    if (endpoint && endpoint !== current && endpointOrder.indexOf(endpoint) >= 0) showEndpoint(endpoint);
    selectGraphNode(nodeId);
    return true;
  }

  cy.on("tap", "node", function (event) { selectItem(event.target.id()); });
  select.addEventListener("change", function () { showEndpoint(select.value); });
  applyTheme();
  var scheme = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  if (scheme && scheme.addEventListener) scheme.addEventListener("change", applyTheme);

  // --- 3. 클래스 격자 ---
  (function renderGrid() {
    var box = document.getElementById("det-grid");
    var noFields = [];
    factors.endpoints.forEach(function (entry) {
      if (!entry.fields.length) { noFields.push(entry.endpoint); return; }
      box.appendChild(el("h3", entry.endpoint));
      var wrap = el("div", null, "scroll");
      var table = el("table", null, "grid-table");
      var body = el("tbody");
      entry.fields.forEach(function (field) {
        var row = el("tr");
        var head = el("th", field.field);
        head.setAttribute("scope", "row");
        row.appendChild(head);
        field.classes.forEach(function (klass) {
          var agg = classAggregate(klass.id) || { state: "empty", cases: [], boundaryCases: 0, unresolved: [] };
          var cell = el("td", null, "cell");
          cell.setAttribute("data-class-id", klass.id);
          cell.setAttribute("data-state", agg.state);
          cell.tabIndex = 0;
          cell.appendChild(symbol(agg.state));
          cell.appendChild(document.createTextNode(" "));
          cell.appendChild(el("code", klass.label));
          if (agg.cases.length) {
            // 칸에는 앞 4개만 적고 나머지는 수로 줄인다(전체 목록은 칸을 누르면 패널에 보인다).
            var shown = agg.cases.slice(0, 4).join(", ");
            var more = agg.cases.length > 4 ? " 외 " + (agg.cases.length - 4) + "건" : "";
            cell.appendChild(el("small", "케이스 " + agg.cases.length + ": " + shown + more));
          }
          if (agg.boundaryCases) cell.appendChild(el("small", "경계 " + agg.boundaryCases));
          if (agg.unresolved.length) {
            cell.appendChild(el("small", "생성 불가 " + agg.unresolved.map(function (u) { return "#" + u.index + " " + u.reason; }).join(", ")));
          }
          cell.addEventListener("click", function () { selectItem(klass.id); });
          cell.addEventListener("keydown", function (event) { if (event.key === "Enter") selectItem(klass.id); });
          row.appendChild(cell);
        });
        body.appendChild(row);
      });
      table.appendChild(body);
      wrap.appendChild(table);
      box.appendChild(wrap);
    });
    if (noFields.length) box.appendChild(el("p", "요청 필드가 없는 엔드포인트: " + noFields.join(", "), "muted"));
  })();

  // --- 4. 2-way 히트맵 ---
  (function renderHeatmap() {
    var box = document.getElementById("det-heatmap");
    factors.endpoints.forEach(function (entry) {
      var pairs = (aggregates.byEndpoint[entry.endpoint] || {}).pairs;
      if (!pairs || !pairs.matrix.length) return;
      var classesOf = {};
      entry.fields.forEach(function (field) { classesOf[field.field] = field.classes; });
      var details = el("details", null, "heat-ep");
      details.appendChild(el("summary", entry.endpoint + " · 쌍 " + pairs.covered + "/" + pairs.total + " · 행렬 " + pairs.matrix.length + "개"));
      pairs.matrix.forEach(function (item) {
        var block = el("div", null, "pair");
        block.setAttribute("data-pair", item.a + "|" + item.b);
        block.appendChild(el("h4", item.a + " × " + item.b));
        var max = 0;
        item.counts.forEach(function (row) { row.forEach(function (count) { if (count > max) max = count; }); });
        var wrap = el("div", null, "scroll");
        var table = el("table", null, "heat");
        var head = el("tr");
        head.appendChild(el("th", shortField(item.a) + " \\ " + shortField(item.b)));
        (classesOf[item.b] || []).forEach(function (klass) { head.appendChild(el("th", klass.label)); });
        var thead = el("thead");
        thead.appendChild(head);
        table.appendChild(thead);
        var body = el("tbody");
        item.counts.forEach(function (row, i) {
          var tr = el("tr");
          var label = el("th", ((classesOf[item.a] || [])[i] || {}).label || String(i));
          label.setAttribute("scope", "row");
          tr.appendChild(label);
          row.forEach(function (count) {
            var td = el("td", count, "num");
            if (count > 0 && max > 0) {
              td.style.setProperty("background", "color-mix(in srgb, var(--accent) " + Math.round(15 + 55 * count / max) + "%, transparent)");
            }
            tr.appendChild(td);
          });
          body.appendChild(tr);
        });
        table.appendChild(body);
        wrap.appendChild(table);
        block.appendChild(wrap);
        details.appendChild(block);
      });
      box.appendChild(details);
    });
    if (!box.firstChild) box.appendChild(el("p", "필드 쌍이 있는 엔드포인트가 없다.", "muted"));
  })();

  // --- 5. 모델 밖 케이스 ---
  (function renderOutOfModel() {
    var box = document.getElementById("det-out");
    var groups = {};
    Object.keys(factors.cases || {}).sort().forEach(function (caseId) {
      var entry = factors.cases[caseId];
      if (entry.inModel) return;
      var key = entry.outReason + "\u0000" + entry.rule;
      (groups[key] = groups[key] || { reason: entry.outReason, rule: entry.rule, cases: [] }).cases.push(caseId);
    });
    var keys = Object.keys(groups).sort();
    if (!keys.length) { box.appendChild(el("p", "모델 밖 케이스가 없다.", "muted")); return; }
    var wrap = el("div", null, "scroll");
    var table = el("table");
    var head = el("tr");
    ["outReason", "규칙", "케이스 수", "케이스"].forEach(function (text) { head.appendChild(el("th", text)); });
    var thead = el("thead");
    thead.appendChild(head);
    table.appendChild(thead);
    var body = el("tbody");
    keys.forEach(function (key) {
      var group = groups[key];
      var tr = el("tr");
      tr.setAttribute("data-out", group.reason);
      tr.appendChild(el("td", group.reason));
      tr.appendChild(el("td", group.rule));
      tr.appendChild(el("td", group.cases.length, "num"));
      tr.appendChild(el("td", group.cases.join(", ")));
      body.appendChild(tr);
    });
    table.appendChild(body);
    wrap.appendChild(table);
    box.appendChild(wrap);
  })();

  // --- 6. 생성 불가 목록 ---
  (function renderUnresolved() {
    var box = document.getElementById("det-unresolved");
    var groups = {};
    factors.unresolved.forEach(function (slot, position) {
      (groups[slot.reason] = groups[slot.reason] || []).push(position);
    });
    var reasons = Object.keys(groups).sort();
    if (!reasons.length) { box.appendChild(el("p", "생성 불가 항목이 없다.", "muted")); return; }
    reasons.forEach(function (reason) {
      box.appendChild(el("h3", reason + " (" + groups[reason].length + ")"));
      var list = el("ul", null, "slot-list");
      groups[reason].forEach(function (position) {
        var slot = factors.unresolved[position];
        var item = el("li");
        item.setAttribute("data-slot", String(slot.index));
        item.appendChild(document.createTextNode("#" + slot.index + " [" + (slotEndpoint(position) || "-") + "] " + slot.rule + " — "));
        item.appendChild(el("code", conditionOf(slot.source) || slot.source));
        list.appendChild(item);
      });
      box.appendChild(list);
    });
  })();

  window.__detviz = { select: selectItem, showEndpoint: showEndpoint };
  if (endpointOrder.length) showEndpoint(endpointOrder[0]);
  window.__td_ready = true;
})();
