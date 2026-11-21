// ext response_dtos: Controller 메서드의 반환 타입 후보. 제네릭 반환(RETURNS_GENERIC)의 타입 인자(중첩 3단계까지)와 비제네릭 RETURNS.
// 스캔한 아티팩트의 타입만 돌려주고, DTO 판정은 td.ontology_ext가 기존 온톨로지의 DTO 노드로 한다.
MATCH (c:Type:Spring:Controller)-[:DECLARES]->(m:Method)-[:RETURNS_GENERIC]->(:ParameterizedType)-[:HAS_ACTUAL_TYPE_ARGUMENT*1..3]->()-[:OF_RAW_TYPE]->(t:Type)
WHERE exists((:Artifact)-[:CONTAINS]->(t))
RETURN DISTINCT c.fqn AS controller, m.name AS handlerName, t.fqn AS type
UNION
MATCH (c:Type:Spring:Controller)-[:DECLARES]->(m:Method)-[:RETURNS]->(t:Type)
WHERE exists((:Artifact)-[:CONTAINS]->(t))
RETURN DISTINCT c.fqn AS controller, m.name AS handlerName, t.fqn AS type
