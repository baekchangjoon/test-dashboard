// Endpoint: Spring :Controller 개념이 붙은 타입의 핸들러 메서드. 클래스 수준 경로(classPaths)와 메서드 수준 경로(methodPaths)는
// 배열 값을 펼친 채로 돌려주고, 결합과 정규화는 td.ontology_jqa.normalize_path가 한다.
MATCH (c:Type:Spring:Controller)-[:DECLARES]->(m:Method)-[:ANNOTATED_BY]->(a:Annotation)-[:OF_TYPE]->(at:Type)
WHERE at.fqn IN [
  'org.springframework.web.bind.annotation.RequestMapping',
  'org.springframework.web.bind.annotation.GetMapping',
  'org.springframework.web.bind.annotation.PostMapping',
  'org.springframework.web.bind.annotation.PutMapping',
  'org.springframework.web.bind.annotation.DeleteMapping',
  'org.springframework.web.bind.annotation.PatchMapping']
OPTIONAL MATCH (c)-[:ANNOTATED_BY]->(ca:Annotation)-[:OF_TYPE]->(:Type {fqn: 'org.springframework.web.bind.annotation.RequestMapping'})
RETURN DISTINCT
  c.fqn AS controller,
  c:RestController AS rest,
  [(ca)-[:HAS]->(arr:Value)-[:CONTAINS]->(e:Value) WHERE arr.name IN ['value', 'path'] AND e.value IS NOT NULL | e.value] AS classPaths,
  [(a)-[:HAS]->(arr2:Value)-[:CONTAINS]->(e2:Value) WHERE arr2.name IN ['value', 'path'] AND e2.value IS NOT NULL | e2.value] AS methodPaths,
  m.name AS handlerName,
  at.fqn AS annotation,
  [(a)-[:HAS]->(ma:Value {name: 'method'})-[:CONTAINS]->(me:Value)-[:IS]->(mf:Field) | mf.name] AS httpMethods
ORDER BY controller, handlerName
