// 대체 경로: Spring 개념 없이 원시 애노테이션과 상속으로 구성요소를 찾는다. 열은 call_paths.cypher와 같다.
MATCH (t:Type)-[:ANNOTATED_BY]->(:Annotation)-[:OF_TYPE]->(at:Type)
WHERE at.fqn IN ['org.springframework.stereotype.Controller', 'org.springframework.web.bind.annotation.RestController',
                 'org.springframework.stereotype.Service', 'org.springframework.stereotype.Repository']
RETURN DISTINCT 'node' AS rowType, t.fqn AS source,
  CASE WHEN at.fqn ENDS WITH 'Service' THEN 'Service' WHEN at.fqn ENDS WITH 'Repository' THEN 'Repository' ELSE 'Controller' END AS sourceKind,
  null AS target, null AS targetKind, at.fqn ENDS WITH 'RestController' AS rest
UNION ALL
MATCH (t:Type)-[:EXTENDS|IMPLEMENTS*1..3]->(r:Type)
WHERE r.fqn IN ['org.springframework.data.repository.Repository', 'org.springframework.data.jpa.repository.JpaRepository']
RETURN DISTINCT 'node' AS rowType, t.fqn AS source, 'Repository' AS sourceKind, null AS target, null AS targetKind, false AS rest
