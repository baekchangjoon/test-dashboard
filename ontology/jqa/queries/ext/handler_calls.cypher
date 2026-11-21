// ext handler_calls: Controller 메서드가 직접 INVOKES하는 Service 메서드. 엔드포인트 대응은 td.ontology_ext가 기존 온톨로지로 한다.
MATCH (c:Type:Spring:Controller)-[:DECLARES]->(m:Method)-[:INVOKES]->(sm:Method)<-[:DECLARES]-(s:Type:Spring:Service)
RETURN DISTINCT c.fqn AS controller, m.name AS handlerName, s.fqn AS service, sm.name AS method
ORDER BY controller, handlerName, service, method
