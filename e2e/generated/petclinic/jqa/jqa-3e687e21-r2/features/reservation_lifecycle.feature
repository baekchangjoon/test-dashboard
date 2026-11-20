Feature: Boarding reservation lifecycle
  Reservations can be created, read back, updated and deleted through the reservation API.

  Scenario: Creating a valid reservation returns an identifier
    Given a unique boarding reservation payload is prepared
    When the boarding reservation is submitted
    Then the boarding reservation request succeeds
    And the boarding reservation response carries an identifier

  Scenario: A created reservation can be read back with the submitted values
    Given a boarding reservation has been created
    When the created boarding reservation is fetched by id
    Then the boarding reservation request succeeds
    And the fetched boarding reservation matches the submitted pet name and owner email

  Scenario: Creating a reservation with the WELCOME10 promo code succeeds
    Given a unique boarding reservation payload is prepared with promo code "WELCOME10"
    When the boarding reservation is submitted
    Then the boarding reservation request succeeds
    And the boarding reservation response carries an identifier

  Scenario: Updating the number of nights of a reservation is persisted
    Given a boarding reservation has been created
    When the boarding reservation is updated to 5 nights
    Then the boarding reservation request succeeds
    And fetching the boarding reservation again shows 5 nights

  Scenario: A deleted reservation can no longer be fetched
    Given a boarding reservation has been created
    When the created boarding reservation is deleted
    Then the boarding reservation request succeeds
    And fetching the deleted boarding reservation returns status 404

  Scenario: Fetching an unknown reservation returns not found
    When a boarding reservation with an unknown id is fetched
    Then the boarding reservation response status is 404

  Scenario: Deleting an unknown reservation is rejected
    When a boarding reservation with an unknown id is deleted
    Then the boarding reservation request is rejected with a client error

  Scenario: Updating an unknown reservation is rejected
    When a boarding reservation with an unknown id is updated
    Then the boarding reservation request is rejected with a client error
