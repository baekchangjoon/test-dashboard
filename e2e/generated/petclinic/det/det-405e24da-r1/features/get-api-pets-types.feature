Feature: GET /api/pets/types
  Deterministic cases derived from the analysis inputs for one endpoint.

  Background:
    Given the SUT timezone is "Asia/Seoul"

  @case:get-api-pets-types-auth-1
  Scenario: get-api-pets-types-auth-1
    Given the case "get-api-pets-types-auth-1"
    And a request to "GET /api/pets/types"
    And the request is sent without authentication
    When the request is sent
    Then the response status is 403

  @case:get-api-pets-types-happy-1
  Scenario: get-api-pets-types-happy-1
    Given the case "get-api-pets-types-happy-1"
    And a request to "GET /api/pets/types"
    When the request is sent
    Then the response status is in class "2xx"
