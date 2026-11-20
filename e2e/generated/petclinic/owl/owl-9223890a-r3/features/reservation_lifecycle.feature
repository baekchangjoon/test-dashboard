Feature: Boarding reservation lifecycle
  Boarding reservations can be created, read back, updated and deleted through the API.

  Scenario: Create a boarding reservation and read it back
    Given a valid boarding reservation request with a unique pet name
    When the boarding reservation is submitted
    Then the boarding reservation is created with an id
    And reading the boarding reservation by id returns the submitted pet name and nights

  Scenario: Create a boarding reservation with the WELCOME10 promo code
    Given a valid boarding reservation request with a unique pet name
    And the boarding reservation request uses promo code "WELCOME10"
    When the boarding reservation is submitted
    Then the boarding reservation is created with an id
    And reading the boarding reservation by id returns the submitted pet name and nights

  Scenario: Update the number of nights of a boarding reservation
    Given an existing boarding reservation created through the API
    When the boarding reservation nights are updated to 3
    Then the boarding reservation update succeeds
    And reading the boarding reservation by id shows 3 nights

  Scenario: Delete a boarding reservation
    Given an existing boarding reservation created through the API
    When the boarding reservation is deleted
    Then the boarding reservation deletion succeeds
    And reading the deleted boarding reservation returns status 404
