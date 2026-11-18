// Controller -> Service -> Repository 호출 경로. rowType=node는 구성요소 자체, edge는 타입 수준 의존이다.
MATCH (t:Type:Spring)
WHERE t:Controller OR t:Service OR t:Repository
RETURN 'node' AS rowType, t.fqn AS source,
  CASE WHEN t:Repository THEN 'Repository' WHEN t:Service THEN 'Service' ELSE 'Controller' END AS sourceKind,
  null AS target, null AS targetKind, t:RestController AS rest
UNION ALL
MATCH (s:Type:Spring)-[:DEPENDS_ON]->(t:Type:Spring)
WHERE s <> t AND (s:Controller OR s:Service) AND (t:Service OR t:Repository)
RETURN 'edge' AS rowType, s.fqn AS source,
  CASE WHEN s:Service THEN 'Service' ELSE 'Controller' END AS sourceKind,
  t.fqn AS target, CASE WHEN t:Repository THEN 'Repository' ELSE 'Service' END AS targetKind, false AS rest
