# Task: write black-box BDD end-to-end tests for a REST API

You are a senior test engineer. Write executable Cucumber (Gherkin) feature files and the Java step
definitions that run them against a running instance of a REST API service. You cannot see the
service's source code, documentation, or existing tests, and you cannot run anything. The only
information you have about the service is the input bundle inlined after these instructions.

## The input bundle

Each bundle file appears between `=== FILE: <path> ===` and `=== END FILE ===`.

- `bbtg/*.json` — results of a static analysis of the service: technology stack, authentication
  setup, endpoint-level test plans (parameters, branch values, expected status codes and
  exceptions), derived test data, a dependency map, external calls, and metadata about existing
  test assets. Some fields were deliberately removed before you received them.
- `bbtg/manifest.json` — a summary of the analysis and the list of removed fields.
- `harness/CONTRACT.md` — the test harness API. It is the ONLY way your step code may talk to the
  service, and its rules are mandatory.
- `ontology/*` (present in some runs) — a structural model of the code base: components, endpoints,
  entities and their relationships. Use it to understand which resources exist, how they relate,
  and which operations depend on others.

## Ground rules

1. Use only the bundle. Every endpoint path, HTTP method, request field, parameter and expected
   status code you use must be supported by evidence in the bundle. Do not rely on prior knowledge
   of any existing application, even if the service looks familiar; treat it as a system you have
   never seen. When the bundle does not pin down a detail (for example the exact shape of a
   response body), write the weakest assertion that is still meaningful (status code, presence of
   a field, non-empty list) instead of guessing specific values.
2. Test only the HTTP API surface described in the bundle. Requests are relative paths that start
   with `/` (the harness already knows the base URL).
3. Every scenario is independent. A scenario that needs data creates it itself through API calls in
   its `Given` steps, and uses unique values (for example a random suffix generated inside the
   scenario) so that repeated or reordered runs never collide. Never assume that particular records
   already exist, and never depend on data created by another scenario. Cleanup is not required.
4. Authentication is handled by the harness: use `Harness.authed()` for normal calls and
   `Harness.anonymous()` only for scenarios that verify access control. Never handle credentials,
   tokens or login yourself.

## What to cover

Aim for breadth first, then depth:
- every endpoint group in the bundle should get at least one successful-path scenario;
- create/read/update flows where the bundle shows them (create a resource, then read it back and
  check the fields you sent);
- validation and error paths that the bundle documents (missing or invalid input, unknown ids,
  conflicting state), asserting the documented status codes;
- access control where the bundle documents it (an anonymous call to a protected endpoint).

`Scenario Outline` with `Examples` is welcome for input variations; every Examples row counts as
its own scenario. Keep the whole suite focused: roughly 25–45 scenarios in total, spread over
about 5–10 feature files grouped by resource or capability. Prefer fewer, well-grounded scenarios
over many speculative ones.

## File layout (mandatory)

- Feature files: `features/<snake_case_name>.feature`. Use English, ASCII-only `Feature:` and
  `Scenario:` names that describe the behaviour.
- For every feature file there is exactly one step class: `glue/<PascalCase of the file name>Steps.java`
  with `package glue;` (for example `features/item_search.feature` -> `glue/ItemSearchSteps.java`,
  class `ItemSearchSteps`).
- Shared helper code (request builders, random value generators, JSON helpers) may only live in
  `glue/support/<Name>.java` with `package glue.support;`. Helper classes contain plain static
  methods only — no step annotations and no hooks.
- No other files and no other locations.

## Step definition rules (Java 17)

- Available libraries: the harness (`td.harness.Harness`), Cucumber 8.1.0 (`io.cucumber.java.en.*`),
  REST Assured 5.5.1 (`io.restassured.*`), AssertJ (`org.assertj.core.api.Assertions`), and the JDK.
  Nothing else (no Jackson, Gson, Lombok, JUnit assertions or Hamcrest imports).
- Cucumber step expressions are global across all step classes: the same step text must never be
  defined in two classes, and every step used in a feature must be defined in that feature's own
  step class. Make step phrases specific to their feature to avoid accidental clashes and
  ambiguous matches.
- Cucumber creates a new instance of each step class per scenario; keep scenario state (last
  response, created ids) in instance fields. There is no dependency injection between classes, so
  steps of one feature cannot share state with another class.
- Use Cucumber expressions (`{int}`, `{string}`, `{word}`) rather than regular expressions, and make
  sure every parameter in a step expression is a parameter of the Java method in the same order.
- Send JSON bodies with `.contentType("application/json").body(map)` using `java.util.Map`/`List`
  values, or with a JSON string. Read responses with `response.jsonPath()`, `response.statusCode()`
  and `response.header(...)`.
- Extract ids of created resources from the response (body field or `Location` header, whichever
  the bundle indicates) and reuse them in later steps of the same scenario.
- Assert with AssertJ `assertThat(...)`. Every `Then` step must assert something.
- Do not write `@Before`/`@After` hooks, and do not use `@ignore`, `@wip`, `@Disabled` or any other
  tag that excludes scenarios.
- Every file must compile on its own merits: correct imports, no placeholders, no TODOs.

## Output format (strict)

Reply with exactly one JSON object and nothing else — no prose, no explanations, no Markdown code
fences:

{"files": [{"path": "features/<name>.feature", "content": "<file text>"}, {"path": "glue/<Name>Steps.java", "content": "<file text>"}]}

- `path` must follow the file layout above; `content` is the full text of the file.
- Escape the content correctly for JSON (newlines as `\n`, quotes as `\"`, backslashes as `\\`).
- Keep the complete reply under about 80,000 characters so that it is never cut off; reduce the
  number of scenarios rather than exceeding this budget.
