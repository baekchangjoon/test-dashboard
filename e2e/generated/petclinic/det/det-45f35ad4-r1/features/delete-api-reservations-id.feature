Feature: DELETE /api/reservations/{id}
  Deterministic cases derived from the analysis inputs for one endpoint.

  Background:
    Given the SUT timezone is "Asia/Seoul"

  @case:delete-auth-1
  Scenario: delete-auth-1
    Given the case "delete-auth-1"
    And a request to "DELETE /api/reservations/{id}"
    And path variable "id" is 1000000
    And the request is sent without authentication
    When the request is sent
    Then the response status is 403

  @case:delete-no-data-1
  Scenario: delete-no-data-1
    Given the case "delete-no-data-1"
    And a request to "DELETE /api/reservations/{id}"
    And path variable "id" is 1000000
    When the request is sent
    Then the response status is 404
