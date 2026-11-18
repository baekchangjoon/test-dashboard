// 스캔한 코드 안의 예외 타입(jQA Java 플러그인이 붙이는 :Throwable 라벨, 스캔한 Artifact가 담은 타입만), 이를 처리하는 @ExceptionHandler 메서드, 이를 던지는 Controller/Service.
MATCH (:Artifact)-[:CONTAINS]->(x:Type:Throwable)
RETURN 'exception' AS rowType, x.fqn AS source, null AS target, null AS handler
UNION ALL
MATCH (h:Type)-[:DECLARES]->(m:Method)-[:ANNOTATED_BY]->(:Annotation)-[:OF_TYPE]->(:Type {fqn: 'org.springframework.web.bind.annotation.ExceptionHandler'})
MATCH (m)-[:ANNOTATED_BY]->(a:Annotation)-[:OF_TYPE]->(:Type {fqn: 'org.springframework.web.bind.annotation.ExceptionHandler'})
MATCH (a)-[:HAS]->(:Value {name: 'value'})-[:CONTAINS]->(:Value)-[:IS]->(x:Type)
RETURN 'handler' AS rowType, x.fqn AS source, null AS target, h.fqn + '#' + m.name AS handler
UNION ALL
MATCH (:Artifact)-[:CONTAINS]->(x:Type:Throwable)
MATCH (s:Type:Spring)-[:DEPENDS_ON]->(x)
WHERE s:Controller OR s:Service
RETURN 'throws' AS rowType, s.fqn AS source, x.fqn AS target, null AS handler
