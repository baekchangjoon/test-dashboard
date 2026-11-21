// ext enums: 스캔한 아티팩트의 enum 상수(자기 enum 타입의 정적 필드). 합성 필드($VALUES)는 synthetic으로 돌려주고 td.ontology_ext가 뺀다.
MATCH (:Artifact)-[:CONTAINS]->(e:Type:Enum)-[:DECLARES]->(f:Field {static: true})-[:OF_TYPE]->(e)
RETURN e.fqn AS enum, f.name AS name, f.synthetic AS synthetic
ORDER BY enum, name
