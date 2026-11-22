Feature: POST /api/reservations
  Deterministic cases derived from the analysis inputs for one endpoint.

  Background:
    Given the SUT timezone is "Asia/Seoul"

  @case:create-auth-1
  Scenario: create-auth-1
    Given the case "create-auth-1"
    And a request to "POST /api/reservations"
    And the request is sent without authentication
    When the request is sent
    Then the response status is 403

  @case:create-baseline-valid-1
  Scenario: create-baseline-valid-1
    Given the case "create-baseline-valid-1"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-baseline-valid-1"
    And body field "roomNumber" is 136
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-branch-entry-1
  Scenario: create-branch-entry-1
    Given the case "create-branch-entry-1"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "WELCOME10"
    And body field "roomNumber" is 288
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-empty-body-1
  Scenario: create-empty-body-1
    Given the case "create-empty-body-1"
    And a request to "POST /api/reservations"
    And the request has no body
    When the request is sent
    Then the response status is in class "4xx"

  @case:create-enum-value-1
  Scenario: create-enum-value-1
    Given the case "create-enum-value-1"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "PREMIUM"
    And body field "promoCode" is "uniq:create-enum-value-1"
    And body field "roomNumber" is 190
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-enum-value-2
  Scenario: create-enum-value-2
    Given the case "create-enum-value-2"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "VIP"
    And body field "promoCode" is "uniq:create-enum-value-2"
    And body field "roomNumber" is 165
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-valid-boundary-1
  Scenario: create-valid-boundary-1
    Given the case "create-valid-boundary-1"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-valid-boundary-1"
    And body field "roomNumber" is 480
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-valid-boundary-2
  Scenario: create-valid-boundary-2
    Given the case "create-valid-boundary-2"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-valid-boundary-2"
    And body field "roomNumber" is 351
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-valid-boundary-3
  Scenario: create-valid-boundary-3
    Given the case "create-valid-boundary-3"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 30
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-valid-boundary-3"
    And body field "roomNumber" is 190
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-valid-boundary-4
  Scenario: create-valid-boundary-4
    Given the case "create-valid-boundary-4"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-valid-boundary-4"
    And body field "roomNumber" is 100
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-valid-boundary-5
  Scenario: create-valid-boundary-5
    Given the case "create-valid-boundary-5"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-valid-boundary-5"
    And body field "roomNumber" is 499
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-valid-boundary-6
  Scenario: create-valid-boundary-6
    Given the case "create-valid-boundary-6"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-valid-boundary-6"
    And body field "roomNumber" is 491
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-valid-boundary-7
  Scenario: create-valid-boundary-7
    Given the case "create-valid-boundary-7"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 4
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-valid-boundary-7"
    And body field "roomNumber" is 223
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-valid-boundary-8
  Scenario: create-valid-boundary-8
    Given the case "create-valid-boundary-8"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-valid-boundary-8"
    And body field "roomNumber" is 266
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-valid-boundary-9
  Scenario: create-valid-boundary-9
    Given the case "create-valid-boundary-9"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-valid-boundary-9"
    And body field "roomNumber" is 219
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-valid-boundary-10
  Scenario: create-valid-boundary-10
    Given the case "create-valid-boundary-10"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "6392bb1ed13afaf7cb545e7ef2401732c9d7e9fcc37e1c2905"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-valid-boundary-10"
    And body field "roomNumber" is 429
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-valid-boundary-11
  Scenario: create-valid-boundary-11
    Given the case "create-valid-boundary-11"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-valid-boundary-11"
    And body field "roomNumber" is 358
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-valid-boundary-12
  Scenario: create-valid-boundary-12
    Given the case "create-valid-boundary-12"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 499
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-valid-boundary-12"
    And body field "roomNumber" is 131
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-valid-boundary-13
  Scenario: create-valid-boundary-13
    Given the case "create-valid-boundary-13"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "VIP"
    And body field "promoCode" is "uniq:create-valid-boundary-13"
    And body field "roomNumber" is 470
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-valid-boundary-14
  Scenario: create-valid-boundary-14
    Given the case "create-valid-boundary-14"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-valid-boundary-14"
    And body field "roomNumber" is 419
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-valid-boundary-15
  Scenario: create-valid-boundary-15
    Given the case "create-valid-boundary-15"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-valid-boundary-15"
    And body field "roomNumber" is 182
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-valid-boundary-16
  Scenario: create-valid-boundary-16
    Given the case "create-valid-boundary-16"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-valid-boundary-16"
    And body field "roomNumber" is 461
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-valid-boundary-17
  Scenario: create-valid-boundary-17
    Given the case "create-valid-boundary-17"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-valid-boundary-17"
    And body field "roomNumber" is 439
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-violation-1
  Scenario: create-violation-1
    Given the case "create-violation-1"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 0
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-violation-1"
    And body field "roomNumber" is 222
    When the request is sent
    Then the response status is 422

  @case:create-violation-2
  Scenario: create-violation-2
    Given the case "create-violation-2"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 0
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-violation-2"
    And body field "roomNumber" is 228
    When the request is sent
    Then the response status is 422

  @case:create-violation-3
  Scenario: create-violation-3
    Given the case "create-violation-3"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 31
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-violation-3"
    And body field "roomNumber" is 230
    When the request is sent
    Then the response status is 422

  @case:create-violation-4
  Scenario: create-violation-4
    Given the case "create-violation-4"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-violation-4"
    And body field "roomNumber" is 99
    When the request is sent
    Then the response status is 422

  @case:create-violation-5
  Scenario: create-violation-5
    Given the case "create-violation-5"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-violation-5"
    And body field "roomNumber" is 500
    When the request is sent
    Then the response status is 422

  @case:create-violation-6
  Scenario: create-violation-6
    Given the case "create-violation-6"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 0
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-violation-6"
    And body field "roomNumber" is 164
    When the request is sent
    Then the response status is 422

  @case:create-violation-7
  Scenario: create-violation-7
    Given the case "create-violation-7"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 5
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-violation-7"
    And body field "roomNumber" is 458
    When the request is sent
    Then the response status is 422

  @case:create-violation-8
  Scenario: create-violation-8
    Given the case "create-violation-8"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is null
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-violation-8"
    And body field "roomNumber" is 221
    When the request is sent
    Then the response status is 422

  @case:create-violation-9
  Scenario: create-violation-9
    Given the case "create-violation-9"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "a"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-violation-9"
    And body field "roomNumber" is 456
    When the request is sent
    Then the response status is 422

  @case:create-violation-10
  Scenario: create-violation-10
    Given the case "create-violation-10"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "9090ff2fa1b78ee3b828002b269ce46b33c835d7bb4e743b676"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-violation-10"
    And body field "roomNumber" is 270
    When the request is sent
    Then the response status is 422

  @case:create-violation-11
  Scenario: create-violation-11
    Given the case "create-violation-11"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is null
    And body field "promoCode" is "uniq:create-violation-11"
    And body field "roomNumber" is 363
    When the request is sent
    Then the response status is 422

  @case:create-violation-12
  Scenario: create-violation-12
    Given the case "create-violation-12"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 499
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "VIP"
    And body field "promoCode" is "uniq:create-violation-12"
    And body field "roomNumber" is 272
    When the request is sent
    Then the response status is 422

  @case:create-violation-13
  Scenario: create-violation-13
    Given the case "create-violation-13"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is null
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-violation-13"
    And body field "roomNumber" is 270
    When the request is sent
    Then the response status is 422

  @case:create-violation-14
  Scenario: create-violation-14
    Given the case "create-violation-14"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "not-an-email"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-violation-14"
    And body field "roomNumber" is 466
    When the request is sent
    Then the response status is 422

  @case:create-violation-15
  Scenario: create-violation-15
    Given the case "create-violation-15"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is null
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-violation-15"
    And body field "roomNumber" is 343
    When the request is sent
    Then the response status is 422

  @case:create-violation-16
  Scenario: create-violation-16
    Given the case "create-violation-16"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-violation-16"
    And body field "roomNumber" is 320
    When the request is sent
    Then the response status is 422

  @case:create-violation-17
  Scenario: create-violation-17
    Given the case "create-violation-17"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today-1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-violation-17"
    And body field "roomNumber" is 351
    When the request is sent
    Then the response status is 422

  @case:create-pairwise-1
  Scenario: create-pairwise-1
    Given the case "create-pairwise-1"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 4
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "6392bb1ed13afaf7cb545e7ef2401732c9d7e9fcc37e1c2905"
    And body field "priceTier" is "VIP"
    And body field "promoCode" is "WELCOME10"
    And body field "roomNumber" is 312
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-pairwise-2
  Scenario: create-pairwise-2
    Given the case "create-pairwise-2"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 4
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 499
    And body field "nights" is 30
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-pairwise-2"
    And body field "roomNumber" is 427
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-pairwise-3
  Scenario: create-pairwise-3
    Given the case "create-pairwise-3"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "PREMIUM"
    And body field "promoCode" is "uniq:create-pairwise-3"
    And body field "roomNumber" is 204
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-pairwise-4
  Scenario: create-pairwise-4
    Given the case "create-pairwise-4"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 4
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 499
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "WELCOME10"
    And body field "roomNumber" is 404
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-pairwise-5
  Scenario: create-pairwise-5
    Given the case "create-pairwise-5"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 4
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "6392bb1ed13afaf7cb545e7ef2401732c9d7e9fcc37e1c2905"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-pairwise-5"
    And body field "roomNumber" is 177
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-pairwise-6
  Scenario: create-pairwise-6
    Given the case "create-pairwise-6"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 30
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "WELCOME10"
    And body field "roomNumber" is 331
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-pairwise-7
  Scenario: create-pairwise-7
    Given the case "create-pairwise-7"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 30
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "VIP"
    And body field "promoCode" is "uniq:create-pairwise-7"
    And body field "roomNumber" is 293
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-pairwise-8
  Scenario: create-pairwise-8
    Given the case "create-pairwise-8"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 4
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 499
    And body field "nights" is 30
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "6392bb1ed13afaf7cb545e7ef2401732c9d7e9fcc37e1c2905"
    And body field "priceTier" is "PREMIUM"
    And body field "promoCode" is "uniq:create-pairwise-8"
    And body field "roomNumber" is 285
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-pairwise-9
  Scenario: create-pairwise-9
    Given the case "create-pairwise-9"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 499
    And body field "nights" is 30
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "6392bb1ed13afaf7cb545e7ef2401732c9d7e9fcc37e1c2905"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "WELCOME10"
    And body field "roomNumber" is 109
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-pairwise-10
  Scenario: create-pairwise-10
    Given the case "create-pairwise-10"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "6392bb1ed13afaf7cb545e7ef2401732c9d7e9fcc37e1c2905"
    And body field "priceTier" is "VIP"
    And body field "promoCode" is "WELCOME10"
    And body field "roomNumber" is 316
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-pairwise-11
  Scenario: create-pairwise-11
    Given the case "create-pairwise-11"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 30
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "6392bb1ed13afaf7cb545e7ef2401732c9d7e9fcc37e1c2905"
    And body field "priceTier" is "PREMIUM"
    And body field "promoCode" is "WELCOME10"
    And body field "roomNumber" is 144
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-pairwise-12
  Scenario: create-pairwise-12
    Given the case "create-pairwise-12"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 4
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 30
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "6392bb1ed13afaf7cb545e7ef2401732c9d7e9fcc37e1c2905"
    And body field "priceTier" is "VIP"
    And body field "promoCode" is "uniq:create-pairwise-12"
    And body field "roomNumber" is 172
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-pairwise-13
  Scenario: create-pairwise-13
    Given the case "create-pairwise-13"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 4
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 30
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "VIP"
    And body field "promoCode" is "WELCOME10"
    And body field "roomNumber" is 445
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-pairwise-14
  Scenario: create-pairwise-14
    Given the case "create-pairwise-14"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "VIP"
    And body field "promoCode" is "uniq:create-pairwise-14"
    And body field "roomNumber" is 327
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-pairwise-15
  Scenario: create-pairwise-15
    Given the case "create-pairwise-15"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 499
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "6392bb1ed13afaf7cb545e7ef2401732c9d7e9fcc37e1c2905"
    And body field "priceTier" is "BASIC"
    And body field "promoCode" is "uniq:create-pairwise-15"
    And body field "roomNumber" is 446
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-pairwise-16
  Scenario: create-pairwise-16
    Given the case "create-pairwise-16"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 1
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 499
    And body field "nights" is 30
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "PREMIUM"
    And body field "promoCode" is "WELCOME10"
    And body field "roomNumber" is 348
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-pairwise-17
  Scenario: create-pairwise-17
    Given the case "create-pairwise-17"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 4
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 499
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "87"
    And body field "priceTier" is "PREMIUM"
    And body field "promoCode" is "WELCOME10"
    And body field "roomNumber" is 289
    When the request is sent
    Then the response status is in class "2xx"

  @case:create-pairwise-18
  Scenario: create-pairwise-18
    Given the case "create-pairwise-18"
    And a request to "POST /api/reservations"
    And body field "animalCount" is 4
    And body field "checkInDate" is "today+1"
    And body field "depositAmount" is 1000000
    And body field "loyaltyPoints" is 500
    And body field "nights" is 1
    And body field "ownerEmail" is "uniq@example.com"
    And body field "petName" is "6392bb1ed13afaf7cb545e7ef2401732c9d7e9fcc37e1c2905"
    And body field "priceTier" is "PREMIUM"
    And body field "promoCode" is "uniq:create-pairwise-18"
    And body field "roomNumber" is 496
    When the request is sent
    Then the response status is in class "2xx"
