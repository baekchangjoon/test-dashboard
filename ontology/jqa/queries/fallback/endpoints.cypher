// 대체 경로: Spring 개념(:Spring:Controller)이 비면 원시 :Annotation 노드로 컨트롤러를 찾는다. 열은 endpoints.cypher와 같다.
MATCH (c:Type)-[:ANNOTATED_BY]->(:Annotation)-[:OF_TYPE]->(ct:Type)
WHERE ct.fqn IN ['org.springframework.stereotype.Controller', 'org.springframework.web.bind.annotation.RestController']
WITH DISTINCT c
MATCH (c)-[:DECLARES]->(m:Method)-[:ANNOTATED_BY]->(a:Annotation)-[:OF_TYPE]->(at:Type)
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
  exists((c)-[:ANNOTATED_BY]->(:Annotation)-[:OF_TYPE]->(:Type {fqn: 'org.springframework.web.bind.annotation.RestController'})) AS rest,
  [(ca)-[:HAS]->(arr:Value)-[:CONTAINS]->(e:Value) WHERE arr.name IN ['value', 'path'] AND e.value IS NOT NULL | e.value] AS classPaths,
  [(a)-[:HAS]->(arr2:Value)-[:CONTAINS]->(e2:Value) WHERE arr2.name IN ['value', 'path'] AND e2.value IS NOT NULL | e2.value] AS methodPaths,
  m.name AS handlerName,
  at.fqn AS annotation,
  [(a)-[:HAS]->(ma:Value {name: 'method'})-[:CONTAINS]->(me:Value)-[:IS]->(mf:Field) | mf.name] AS httpMethods
ORDER BY controller, handlerName
