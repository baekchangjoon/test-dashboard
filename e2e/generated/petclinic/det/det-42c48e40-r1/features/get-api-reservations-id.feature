Feature: GET /api/reservations/{id}
  Deterministic cases derived from the analysis inputs for one endpoint.

  Background:
    Given the SUT timezone is "Asia/Seoul"

  @case:getbyid-auth-1
  Scenario: getbyid-auth-1
    Given the case "getbyid-auth-1"
    And a request to "GET /api/reservations/{id}"
    And path variable "id" is 1000000
    And the request is sent without authentication
    When the request is sent
    Then the response status is 403

  @case:getbyid-happy-1
  Scenario: getbyid-happy-1
    Given the case "getbyid-happy-1"
    And a prior request to "POST /api/reservations" with body {"animalCount": 1, "checkInDate": "today+1", "depositAmount": 1000000, "loyaltyPoints": 500, "nights": 1, "ownerEmail": "uniq@example.com", "petName": "87", "priceTier": "BASIC", "promoCode": "uniq:getbyid-happy-1", "roomNumber": 474} capturing "id" as "id"
    And a request to "GET /api/reservations/{id}"
    And path variable "id" is "ref:id"
    And query parameter "includeStale" is true
    When the request is sent
    Then the response status is in class "2xx"

  @case:getbyid-no-data-1
  Scenario: getbyid-no-data-1
    Given the case "getbyid-no-data-1"
    And a request to "GET /api/reservations/{id}"
    And path variable "id" is 1000000
    And query parameter "includeStale" is true
    When the request is sent
    Then the response status is 404
