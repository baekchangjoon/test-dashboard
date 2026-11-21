// test-dashboard 새 디자인(v2) 스크립트. 서버가 HTML을 먼저 그리고, 이 스크립트는 페이지에 있는 요소만 보고 덧입힌다.
// 스크립트가 꺼져도 모든 내용이 보인다(예: 단계 설명은 전부 펼쳐진 채로 남는다).
(function () {
  "use strict";
  document.documentElement.classList.add("js");

  // --- 단계 띠: 단계를 누르면 그 단계의 설명만 보인다 ------------------------------------------
  function setupStageStrip(strip) {
    var detail = document.getElementById("stage-detail");
    if (!detail) return;
    var buttons = Array.prototype.slice.call(strip.querySelectorAll("button[data-stage]"));
    function select(stageId) {
      buttons.forEach(function (button) {
        button.setAttribute("aria-pressed", String(button.dataset.stage === stageId));
      });
      Array.prototype.forEach.call(detail.querySelectorAll("[data-detail]"), function (item) {
        item.classList.toggle("on", item.dataset.detail === stageId);
      });
    }
    buttons.forEach(function (button, position) {
      button.addEventListener("click", function () { select(button.dataset.stage); });
      button.addEventListener("keydown", function (event) {
        var step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
        if (!step) return;
        event.preventDefault();
        var next = buttons[(position + step + buttons.length) % buttons.length];
        next.focus();
        select(next.dataset.stage);
      });
    });
    var pressed = strip.querySelector('button[aria-pressed="true"]') || buttons[0];
    if (pressed) select(pressed.dataset.stage);
  }

  // --- 게시 결과(S13): publish-log를 읽어 보여 준다(없으면 "게시 결과 없음" 유지) ---------------------
  var STATUS_CLASS = { passed: "s-good", degraded: "s-warn", failed: "s-crit" };

  function updateS13(log) {
    if (!log.status) return;
    var button = document.querySelector('#stage-strip button[data-stage="S13"]');
    if (button) {
      button.dataset.status = log.status;
      button.classList.remove("s-good", "s-warn", "s-crit", "s-none");
      button.classList.add(STATUS_CLASS[log.status] || "s-none");
    }
    var item = document.querySelector('#stage-detail [data-detail="S13"]');
    if (!item) return;
    var badge = item.querySelector(".st");
    if (badge) {
      badge.textContent = log.status;
      badge.classList.remove("s-good", "s-warn", "s-crit", "s-none");
      badge.classList.add(STATUS_CLASS[log.status] || "s-none");
    }
    var reason = item.querySelector(".stage-reason");
    if (reason) reason.textContent = log.reason || "";
  }

  function setupPublishResult(box) {
    if (!box.dataset.url || !window.fetch) return;
    fetch(box.dataset.url, { cache: "no-cache" }).then(function (response) {
      if (!response.ok) throw new Error(String(response.status));
      return response.json();
    }).then(function (log) {
      box.textContent = "";
      var list = document.createElement("ul");
      function item(text) { var li = document.createElement("li"); li.textContent = text; list.appendChild(li); }
      item("상태: " + (log.status || "알 수 없음"));
      if (log.reason) item("사유: " + log.reason);
      var hosts = log.hosts || {};
      Object.keys(hosts).sort().forEach(function (name) {
        var host = hosts[name];
        item(name + ": " + (host && typeof host === "object" ? (host.status || JSON.stringify(host)) : String(host)));
      });
      box.appendChild(list);
      updateS13(log);
    }).catch(function () { /* 게시 결과 없음 유지 */ });
  }

  var strip = document.getElementById("stage-strip");
  if (strip) setupStageStrip(strip);
  var publishBox = document.getElementById("publish-result");
  if (publishBox) setupPublishResult(publishBox);
})();
