Feature: POST /api/owners
  Deterministic cases derived from the analysis inputs for one endpoint.

  Background:
    Given the SUT timezone is "Asia/Seoul"

  @case:post-api-owners-auth-1
  Scenario: post-api-owners-auth-1
    Given the case "post-api-owners-auth-1"
    And a request to "POST /api/owners"
    And the request is sent without authentication
    When the request is sent
    Then the response status is 403
