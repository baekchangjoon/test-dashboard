// DTO: Controller가 의존하는, 스캔한 코드 안의 타입 중 이름이 Request/Response/Dto로 끝나는 것(엔티티, Spring 구성요소, 예외,
// 열거형, @ControllerAdvice 제외). 이름 규약은 이 PoC의 휴리스틱이다.
// rowType=uses는 핸들러 메서드의 파라미터·반환 타입으로 쓰인 경우다(제네릭 인자는 jQA가 OF_TYPE으로 남기지 않으므로 type 수준 의존으로 둔다).
MATCH (c:Type:Spring:Controller)-[:DEPENDS_ON]->(d:Type)
WHERE exists((:Artifact)-[:CONTAINS]->(d)) AND NOT d:Spring AND NOT d:Enum AND d <> c
  AND NOT exists((d)-[:ANNOTATED_BY]->(:Annotation)-[:OF_TYPE]->(:Type {fqn: 'jakarta.persistence.Entity'}))
  AND NOT exists((d)-[:ANNOTATED_BY]->(:Annotation)-[:OF_TYPE]->(:Type {fqn: 'org.springframework.web.bind.annotation.RestControllerAdvice'}))
  AND NOT exists((d)-[:ANNOTATED_BY]->(:Annotation)-[:OF_TYPE]->(:Type {fqn: 'org.springframework.web.bind.annotation.ControllerAdvice'}))
  AND NOT d:Throwable
  AND d.fqn =~ '.*(Request|Response|Dto|DTO)$'
RETURN 'dto' AS rowType, d.fqn AS source, null AS target, null AS handlerName
UNION ALL
MATCH (c:Type:Spring:Controller)-[:DECLARES]->(m:Method)-[:HAS]->(:Parameter)-[:OF_TYPE]->(d:Type)
WHERE exists((:Artifact)-[:CONTAINS]->(d)) AND NOT d:Spring AND NOT d:Enum
RETURN 'uses' AS rowType, c.fqn AS source, d.fqn AS target, m.name AS handlerName
UNION ALL
MATCH (c:Type:Spring:Controller)-[:DECLARES]->(m:Method)-[:RETURNS]->(d:Type)
WHERE exists((:Artifact)-[:CONTAINS]->(d)) AND NOT d:Spring AND NOT d:Enum
RETURN 'uses' AS rowType, c.fqn AS source, d.fqn AS target, m.name AS handlerName
