# Task: repair Turtle additions for an OWL skeleton ontology

Your previous reply (PREVIOUS OUTPUT) was meant to be Turtle triples that add domain labels,
comments, relation characteristics and OWL restrictions to the skeleton ontology in the input
bundle (appended after these instructions). A program rejected it for the reasons in ERRORS.

Fix only what the errors report and keep everything else of your previous reply. The rules are the
same as before: describe only terms that already exist in `ontology/skeleton.ttl` (or blank-node
`owl:Restriction`s), never write `td:` annotations such as `td:fromJqa` or `td:kind`, never add
`rdfs:domain` or `rdfs:range`, and use only the allowed predicates (`rdf:type` with an OWL property
characteristic or `owl:Restriction`, `rdfs:label`, `rdfs:comment`, `rdfs:subClassOf`, `owl:inverseOf`,
`owl:disjointWith`, and OWL restriction predicates).

Reply with the complete corrected Turtle additions only — no prose and no Markdown code fences. The
prefixes `td:`, `owl:`, `rdf:`, `rdfs:` and `xsd:` are predeclared.

=== ERRORS ===
{{ERRORS}}

=== PREVIOUS OUTPUT ===
{{PREVIOUS_OUTPUT}}
