Feature: GET /api/owners
  Deterministic cases derived from the analysis inputs for one endpoint.

  Background:
    Given the SUT timezone is "Asia/Seoul"

  @case:get-api-owners-auth-1
  Scenario: get-api-owners-auth-1
    Given the case "get-api-owners-auth-1"
    And a request to "GET /api/owners"
    And the request is sent without authentication
    When the request is sent
    Then the response status is 403

  @case:get-api-owners-happy-1
  Scenario: get-api-owners-happy-1
    Given the case "get-api-owners-happy-1"
    And a request to "GET /api/owners"
    When the request is sent
    Then the response status is in class "2xx"
