// 사이트 공통 스크립트. run 페이지는 publish-log를 읽어 S13 결과를 보여 준다(없으면 "게시 결과 없음" 유지).
(function () {
  var box = document.getElementById('publish-result');
  if (!box || !window.fetch) return;
  fetch(box.dataset.url, { cache: 'no-cache' }).then(function (r) {
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  }).then(function (log) {
    box.textContent = '';
    var list = document.createElement('ul');
    function item(text) { var li = document.createElement('li'); li.textContent = text; list.appendChild(li); }
    item('상태: ' + (log.status || '알 수 없음'));
    if (log.reason) item('사유: ' + log.reason);
    var hosts = log.hosts || {};
    Object.keys(hosts).sort().forEach(function (name) {
      var host = hosts[name];
      item(name + ': ' + (host && typeof host === 'object' ? (host.status || JSON.stringify(host)) : String(host)));
    });
    box.appendChild(list);
    // run.json과 같은 값(publishing)으로 렌더된 S13 행을 최종 결과(publish-log)로 바꾼다.
    var row = document.querySelector('#stages tr[data-stage="S13"]');
    if (row && log.status) {
      var cells = row.querySelectorAll('td');
      cells[1].textContent = log.status;
      cells[1].className = 'st-' + log.status;
      cells[2].textContent = log.reason || '';
    }
  }).catch(function () { /* 게시 결과 없음 유지 */ });
})();
