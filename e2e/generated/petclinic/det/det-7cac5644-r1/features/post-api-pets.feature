Feature: POST /api/pets
  Deterministic cases derived from the analysis inputs for one endpoint.

  Background:
    Given the SUT timezone is "Asia/Seoul"

  @case:post-api-pets-auth-1
  Scenario: post-api-pets-auth-1
    Given the case "post-api-pets-auth-1"
    And a request to "POST /api/pets"
    And the request is sent without authentication
    When the request is sent
    Then the response status is 403
