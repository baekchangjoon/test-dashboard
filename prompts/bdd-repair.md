# Task: repair a generated BDD test suite that failed static checks

The Cucumber feature files and Java step definitions below (PREVIOUS FILES) were generated for a
black-box REST API from the input bundle that follows these instructions. They failed static checks
that run without the service: the Java compiler, and a Cucumber dry run that reports steps with no
matching step definition. The only feedback available is listed below; nothing was executed against
the service.

Fix the reported problems:
- Make every step class compile (imports, types, syntax, method signatures that match the step
  expression parameters). Use only the harness (`td.harness.Harness`), Cucumber 8.1.0, REST Assured
  5.5.1, AssertJ and the JDK.
- Make every step in every feature match exactly one step definition in that feature's own step
  class. Step text must not be defined in two classes.
- Keep the file layout: `features/<snake_case_name>.feature`, one `glue/<PascalCase of the file name>Steps.java`
  per feature with `package glue;`, shared static helpers only in `glue/support/` with
  `package glue.support;`. A "layout violation" means a class is in the wrong place or has the wrong
  name.
- Never remove a scenario, a feature file, or an Examples row. Every scenario of the previous files
  must still be present in your reply. If you cannot make a step class compile, leave it as it is:
  its scenarios will be counted as uncompilable, which is the honest outcome. Fix the code instead of
  deleting the tests, and keep the intent of each scenario. Use only information from the bundle, as
  before.

Reply with exactly one JSON object and nothing else — no prose and no Markdown code fences — that
contains the COMPLETE corrected file set (every file, including the ones you did not change):

{"files": [{"path": "features/<name>.feature", "content": "<file text>"}, {"path": "glue/<Name>Steps.java", "content": "<file text>"}]}

Escape the content correctly for JSON and keep the reply under about 80,000 characters.

=== COMPILER OUTPUT ===
{{COMPILER_OUTPUT}}

=== UNDEFINED STEPS ===
{{UNDEFINED_STEPS}}

=== PREVIOUS FILES ===
{{PREVIOUS_FILES}}
