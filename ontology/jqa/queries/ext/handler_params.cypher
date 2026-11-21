// ext handler_params: Controller 메서드 파라미터의 index, 타입, 애노테이션과 그 값(name/value). 애노테이션이 여럿이면 행도 여럿이다.
// 바인딩 종류(PathVariable/RequestParam/RequestBody) 선택은 td.ontology_ext가 한다.
MATCH (c:Type:Spring:Controller)-[:DECLARES]->(m:Method)-[:HAS]->(p:Parameter)-[:ANNOTATED_BY]->(a:Annotation)-[:OF_TYPE]->(at:Type)
OPTIONAL MATCH (p)-[:OF_TYPE]->(t:Type)
RETURN DISTINCT c.fqn AS controller, m.name AS handlerName, p.index AS index, p.name AS parameterName, t.fqn AS type,
  at.fqn AS annotation, [(a)-[:HAS]->(v:Value) | {name: v.name, value: v.value}] AS values
ORDER BY controller, handlerName, index, annotation
