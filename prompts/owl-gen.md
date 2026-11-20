# Task: enrich a generated OWL skeleton ontology of a REST service

You are given an input bundle (appended after these instructions) with two kinds of files:

- `ontology/skeleton.ttl`: an OWL ontology in Turtle that a deterministic program derived from a static
  code graph of the service. It declares one `owl:Class` per persistent entity, per request/response
  data type (DTO) and per REST resource path, one `owl:ObjectProperty` per association between
  entities, one `owl:DatatypeProperty` per entity field, and one `owl:NamedIndividual` per REST
  endpoint. Every term carries `td:fromJqa` (the id of the code-graph node it came from) and
  `td:kind`. Annotations such as `td:jpaRelation`, `td:javaType`, `td:annotation`, `td:httpMethod`,
  `td:path`, `td:requestBody` and `td:relatedEntity` record what the program saw.
- `bbtg/*.json`: static-analysis summaries of the service (stack, endpoints, test data hints, entity
  relations). They contain no source code.

Your job is to add domain meaning to the skeleton, using only what the bundle shows:

1. Domain concept names: give each class, object property and datatype property a short human
   name as an English `rdfs:label` with the `@en` language tag (for example a data type called
   `XyzDtos$CreateXyzRequest` becomes "Xyz creation request"@en). Keep the existing plain labels.
2. Descriptions: add an English `rdfs:comment "..."@en` to classes and properties, saying what the
   concept or relation means in the domain. Be concise (one sentence).
3. Relation semantics: mark object properties with OWL characteristics when the bundle supports it
   (`a owl:FunctionalProperty` for to-one associations, `owl:inverseOf` between two existing object
   properties that are the two sides of one association).
4. Constraints: express field and association constraints visible in the skeleton annotations
   (for example a validation `td:annotation` such as "NotBlank", a to-one or to-many `td:jpaRelation`) as OWL
   restrictions on the owning class:
   `td:SomeClass rdfs:subClassOf [ a owl:Restriction ; owl:onProperty td:SomeClass_field ; owl:minCardinality "1"^^xsd:nonNegativeInteger ] .`
   You may use `owl:minCardinality`, `owl:maxCardinality`, `owl:cardinality`, `owl:someValuesFrom`,
   `owl:allValuesFrom`, `owl:onClass` with `owl:qualifiedCardinality` / `owl:minQualifiedCardinality` /
   `owl:maxQualifiedCardinality`, and `owl:disjointWith` between existing classes.

Rules (the output is checked by a program and rejected when a rule is broken):

- Only describe terms that already exist in `skeleton.ttl` (every subject must be an existing `td:` IRI
  or a blank node that is an `owl:Restriction`). Do not invent new classes, properties or individuals.
- Do not write `td:fromJqa`, `td:kind` or any other `td:` annotation; provenance belongs to the skeleton.
- Do not add `rdfs:domain` or `rdfs:range`; they are already set.
- Allowed predicates: `rdf:type` (only `owl:FunctionalProperty`, `owl:InverseFunctionalProperty`,
  `owl:SymmetricProperty`, `owl:AsymmetricProperty`, `owl:TransitiveProperty`,
  `owl:IrreflexiveProperty`, `owl:ReflexiveProperty`, or `owl:Restriction` on a blank node),
  `rdfs:label`, `rdfs:comment`, `rdfs:subClassOf`, `owl:inverseOf`, `owl:disjointWith`, and the
  restriction predicates listed above.
- Do not rely on prior knowledge of any well-known sample application, even if names look familiar.
  If the bundle does not support a statement, leave it out.

Output format: reply with Turtle only — the additional triples, not the whole ontology — and nothing
else (no prose, no Markdown code fences). The prefixes `td:`, `owl:`, `rdf:`, `rdfs:` and `xsd:` are
predeclared; do not declare other prefixes. Keep the reply under about 40,000 characters.
