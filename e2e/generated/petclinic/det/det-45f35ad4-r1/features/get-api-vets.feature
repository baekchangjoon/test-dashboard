Feature: GET /api/vets
  Deterministic cases derived from the analysis inputs for one endpoint.

  Background:
    Given the SUT timezone is "Asia/Seoul"

  @case:get-api-vets-auth-1
  Scenario: get-api-vets-auth-1
    Given the case "get-api-vets-auth-1"
    And a request to "GET /api/vets"
    And the request is sent without authentication
    When the request is sent
    Then the response status is 403

  @case:get-api-vets-happy-1
  Scenario: get-api-vets-happy-1
    Given the case "get-api-vets-happy-1"
    And a request to "GET /api/vets"
    When the request is sent
    Then the response status is in class "2xx"
