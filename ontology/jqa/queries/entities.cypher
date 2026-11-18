// JPA 엔티티, 필드(@MappedSuperclass 조상 포함, 검증 애노테이션 포함), 엔티티 간 연관, Repository가 다루는 엔티티.
MATCH (e:Type)-[:ANNOTATED_BY]->(:Annotation)-[:OF_TYPE]->(:Type {fqn: 'jakarta.persistence.Entity'})
RETURN 'entity' AS rowType, e.fqn AS source, null AS target, null AS name, null AS type, [] AS annotations
UNION ALL
MATCH (e:Type)-[:ANNOTATED_BY]->(:Annotation)-[:OF_TYPE]->(:Type {fqn: 'jakarta.persistence.Entity'})
MATCH (e)-[:EXTENDS*0..5]->(owner:Type)-[:DECLARES]->(f:Field)
WHERE (owner = e OR exists((owner)-[:ANNOTATED_BY]->(:Annotation)-[:OF_TYPE]->(:Type {fqn: 'jakarta.persistence.MappedSuperclass'})))
  AND coalesce(f.static, false) = false
RETURN 'field' AS rowType, e.fqn AS source, null AS target, f.name AS name,
  head([(f)-[:OF_TYPE]->(ft:Type) | ft.fqn]) AS type,
  [(f)-[:ANNOTATED_BY]->(:Annotation)-[:OF_TYPE]->(at:Type) | at.fqn] AS annotations
UNION ALL
MATCH (e:Type)-[:ANNOTATED_BY]->(:Annotation)-[:OF_TYPE]->(:Type {fqn: 'jakarta.persistence.Entity'})
MATCH (e)-[:DEPENDS_ON]->(o:Type)-[:ANNOTATED_BY]->(:Annotation)-[:OF_TYPE]->(:Type {fqn: 'jakarta.persistence.Entity'})
WHERE e <> o
RETURN 'reference' AS rowType, e.fqn AS source, o.fqn AS target, null AS name, null AS type, [] AS annotations
UNION ALL
MATCH (r:Type:Spring:Repository)-[:DEPENDS_ON]->(o:Type)-[:ANNOTATED_BY]->(:Annotation)-[:OF_TYPE]->(:Type {fqn: 'jakarta.persistence.Entity'})
RETURN 'manages' AS rowType, r.fqn AS source, o.fqn AS target, null AS name, null AS type, [] AS annotations
