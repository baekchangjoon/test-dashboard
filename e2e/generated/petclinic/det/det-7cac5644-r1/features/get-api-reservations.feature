Feature: GET /api/reservations
  Deterministic cases derived from the analysis inputs for one endpoint.

  Background:
    Given the SUT timezone is "Asia/Seoul"

  @case:list-auth-1
  Scenario: list-auth-1
    Given the case "list-auth-1"
    And a request to "GET /api/reservations"
    And the request is sent without authentication
    When the request is sent
    Then the response status is 403

  @case:list-enum-value-1
  Scenario: list-enum-value-1
    Given the case "list-enum-value-1"
    And a request to "GET /api/reservations"
    And query parameter "tier" is "BASIC"
    When the request is sent
    Then the response status is in class "2xx"

  @case:list-enum-value-2
  Scenario: list-enum-value-2
    Given the case "list-enum-value-2"
    And a request to "GET /api/reservations"
    And query parameter "tier" is "PREMIUM"
    When the request is sent
    Then the response status is in class "2xx"

  @case:list-enum-value-3
  Scenario: list-enum-value-3
    Given the case "list-enum-value-3"
    And a request to "GET /api/reservations"
    And query parameter "tier" is "VIP"
    When the request is sent
    Then the response status is in class "2xx"

  @case:list-filter-empty-1
  Scenario: list-filter-empty-1
    Given the case "list-filter-empty-1"
    And a request to "GET /api/reservations"
    And query parameter "minNights" is 1000000
    When the request is sent
    Then the response status is in class "2xx"

  @case:list-filter-empty-2
  Scenario: list-filter-empty-2
    Given the case "list-filter-empty-2"
    And a request to "GET /api/reservations"
    And query parameter "recentOnly" is true
    When the request is sent
    Then the response status is in class "2xx"

  @case:list-happy-1
  Scenario: list-happy-1
    Given the case "list-happy-1"
    And a request to "GET /api/reservations"
    When the request is sent
    Then the response status is in class "2xx"
