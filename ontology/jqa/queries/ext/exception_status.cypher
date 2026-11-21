// ext exception_status: @ExceptionHandler 메서드가 INVOKES하는 ResponseEntity 빌더(ResponseEntity$BodyBuilder 포함)와
// READS하는 HttpStatus 상수. 외부 메서드·필드는 name이 없고 signature만 있으므로 둘 중 있는 것을 돌려준다.
MATCH (h:Type)-[:DECLARES]->(m:Method)-[:ANNOTATED_BY]->(:Annotation)-[:OF_TYPE]->(:Type {fqn: 'org.springframework.web.bind.annotation.ExceptionHandler'})
OPTIONAL MATCH (m)-[:INVOKES]->(b:Method)<-[:DECLARES]-(o:Type)
WHERE o.fqn STARTS WITH 'org.springframework.http.ResponseEntity'
WITH h, m, collect(DISTINCT coalesce(b.name, b.signature)) AS builders
OPTIONAL MATCH (m)-[:READS]->(sf:Field)<-[:DECLARES]-(:Type {fqn: 'org.springframework.http.HttpStatus'})
RETURN DISTINCT h.fqn + '#' + m.name AS handler, builders, collect(DISTINCT coalesce(sf.name, sf.signature)) AS statusFields
ORDER BY handler
