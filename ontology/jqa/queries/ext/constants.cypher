// ext constants: 스캔한 아티팩트의 정적 final 필드 중 바이트코드 ConstantValue가 있는 것(원시·String만 잡힌다).
MATCH (:Artifact)-[:CONTAINS]->(o:Type)-[:DECLARES]->(f:Field {static: true, final: true})-[:HAS]->(v:Value)
OPTIONAL MATCH (f)-[:OF_TYPE]->(t:Type)
RETURN o.fqn AS owner, f.name AS name, t.fqn AS type, v.value AS value, f.synthetic AS synthetic
ORDER BY owner, name
