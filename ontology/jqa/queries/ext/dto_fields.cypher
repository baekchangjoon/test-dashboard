// ext dto_fields: DTO 후보 타입(dtos.cypher와 같은 휴리스틱)이 선언한 비정적·비합성 필드와 그 타입.
// 최종 DTO 집합은 td.ontology_ext가 기존 온톨로지의 DTO 노드로 한정한다.
MATCH (c:Type:Spring:Controller)-[:DEPENDS_ON]->(d:Type)
WHERE exists((:Artifact)-[:CONTAINS]->(d)) AND NOT d:Spring AND NOT d:Enum AND NOT d:Throwable AND d <> c
  AND d.fqn =~ '.*(Request|Response|Dto|DTO)$'
WITH DISTINCT d
MATCH (d)-[:DECLARES]->(f:Field)
WHERE coalesce(f.static, false) = false AND coalesce(f.synthetic, false) = false
OPTIONAL MATCH (f)-[:OF_TYPE]->(t:Type)
RETURN d.fqn AS dto, f.name AS name, t.fqn AS type
ORDER BY dto, name
