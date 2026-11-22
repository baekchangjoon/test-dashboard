Feature: PUT /api/reservations/{id}
  Deterministic cases derived from the analysis inputs for one endpoint.

  Background:
    Given the SUT timezone is "Asia/Seoul"

  @case:update-auth-1
  Scenario: update-auth-1
    Given the case "update-auth-1"
    And a request to "PUT /api/reservations/{id}"
    And path variable "id" is 1000000
    And the request is sent without authentication
    When the request is sent
    Then the response status is 403

  @case:update-baseline-valid-1
  Scenario: update-baseline-valid-1
    Given the case "update-baseline-valid-1"
    And a prior request to "POST /api/reservations" with body {"animalCount": 1, "checkInDate": "today+1", "depositAmount": 1000000, "loyaltyPoints": 500, "nights": 1, "ownerEmail": "uniq@example.com", "petName": "87", "priceTier": "BASIC", "promoCode": "uniq:update-baseline-valid-1", "roomNumber": 387} capturing "id" as "id"
    And a request to "PUT /api/reservations/{id}"
    And path variable "id" is "ref:id"
    When the request is sent
    Then the response status is in class "2xx"

  @case:update-no-data-1
  Scenario: update-no-data-1
    Given the case "update-no-data-1"
    And a request to "PUT /api/reservations/{id}"
    And path variable "id" is 1000000
    When the request is sent
    Then the response status is 404

  @case:update-valid-boundary-1
  Scenario: update-valid-boundary-1
    Given the case "update-valid-boundary-1"
    And a prior request to "POST /api/reservations" with body {"animalCount": 1, "checkInDate": "today+1", "depositAmount": 1000000, "loyaltyPoints": 500, "nights": 1, "ownerEmail": "uniq@example.com", "petName": "87", "priceTier": "BASIC", "promoCode": "uniq:update-valid-boundary-1", "roomNumber": 447} capturing "id" as "id"
    And a request to "PUT /api/reservations/{id}"
    And path variable "id" is "ref:id"
    When the request is sent
    Then the response status is in class "2xx"

  @case:update-valid-boundary-2
  Scenario: update-valid-boundary-2
    Given the case "update-valid-boundary-2"
    And a prior request to "POST /api/reservations" with body {"animalCount": 1, "checkInDate": "today+1", "depositAmount": 1000000, "loyaltyPoints": 500, "nights": 1, "ownerEmail": "uniq@example.com", "petName": "87", "priceTier": "BASIC", "promoCode": "uniq:update-valid-boundary-2", "roomNumber": 230} capturing "id" as "id"
    And a request to "PUT /api/reservations/{id}"
    And path variable "id" is "ref:id"
    And body field "nights" is 1
    When the request is sent
    Then the response status is in class "2xx"

  @case:update-valid-boundary-3
  Scenario: update-valid-boundary-3
    Given the case "update-valid-boundary-3"
    And a prior request to "POST /api/reservations" with body {"animalCount": 1, "checkInDate": "today+1", "depositAmount": 1000000, "loyaltyPoints": 500, "nights": 1, "ownerEmail": "uniq@example.com", "petName": "87", "priceTier": "BASIC", "promoCode": "uniq:update-valid-boundary-3", "roomNumber": 495} capturing "id" as "id"
    And a request to "PUT /api/reservations/{id}"
    And path variable "id" is "ref:id"
    And body field "nights" is 30
    When the request is sent
    Then the response status is in class "2xx"

  @case:update-violation-1
  Scenario: update-violation-1
    Given the case "update-violation-1"
    And a prior request to "POST /api/reservations" with body {"animalCount": 1, "checkInDate": "today+1", "depositAmount": 1000000, "loyaltyPoints": 500, "nights": 1, "ownerEmail": "uniq@example.com", "petName": "87", "priceTier": "BASIC", "promoCode": "uniq:update-violation-1", "roomNumber": 119} capturing "id" as "id"
    And a request to "PUT /api/reservations/{id}"
    And path variable "id" is "ref:id"
    And body field "nights" is 0
    When the request is sent
    Then the response status is 422

  @case:update-violation-2
  Scenario: update-violation-2
    Given the case "update-violation-2"
    And a prior request to "POST /api/reservations" with body {"animalCount": 1, "checkInDate": "today+1", "depositAmount": 1000000, "loyaltyPoints": 500, "nights": 1, "ownerEmail": "uniq@example.com", "petName": "87", "priceTier": "BASIC", "promoCode": "uniq:update-violation-2", "roomNumber": 379} capturing "id" as "id"
    And a request to "PUT /api/reservations/{id}"
    And path variable "id" is "ref:id"
    And body field "nights" is 31
    When the request is sent
    Then the response status is 422
