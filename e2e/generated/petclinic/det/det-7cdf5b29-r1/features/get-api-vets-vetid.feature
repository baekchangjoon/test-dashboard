Feature: GET /api/vets/{vetId}
  Deterministic cases derived from the analysis inputs for one endpoint.

  Background:
    Given the SUT timezone is "Asia/Seoul"

  @case:get-api-vets-vetid-auth-1
  Scenario: get-api-vets-vetid-auth-1
    Given the case "get-api-vets-vetid-auth-1"
    And a request to "GET /api/vets/{vetId}"
    And path variable "vetId" is 1000000
    And the request is sent without authentication
    When the request is sent
    Then the response status is 403

  @case:get-api-vets-vetid-no-data-1
  Scenario: get-api-vets-vetid-no-data-1
    Given the case "get-api-vets-vetid-no-data-1"
    And a request to "GET /api/vets/{vetId}"
    And path variable "vetId" is 1000000
    When the request is sent
    Then the response status is in class "4xx"
