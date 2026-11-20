Feature: Boarding reservation lifecycle

  Scenario: A created reservation can be read back
    Given a boarding reservation has been created with unique data
    When the client retrieves the created boarding reservation
    Then the reservation API responds with status 200
    And the retrieved reservation shows the submitted pet name and owner email

  Scenario: Creating a reservation with the welcome promo code succeeds
    When the client creates a boarding reservation using promo code "WELCOME10"
    Then the promo reservation is created successfully

  Scenario: Updating the nights of a reservation is persisted
    Given a boarding reservation has been created with unique data
    When the client changes the nights of the created boarding reservation to 3
    Then the reservation update is accepted
    And retrieving the created boarding reservation shows 3 nights

  Scenario: Deleting a reservation removes it
    Given a boarding reservation has been created with unique data
    When the client deletes the created boarding reservation
    Then the reservation deletion is accepted
    And retrieving the deleted boarding reservation returns status 404

  Scenario: Retrieving an unknown reservation returns not found
    When the client retrieves a boarding reservation with an unknown id
    Then the reservation API responds with status 404

  Scenario: Updating an unknown reservation returns not found
    When the client updates a boarding reservation with an unknown id
    Then the reservation API responds with status 404

  Scenario: Deleting an unknown reservation returns not found
    When the client deletes a boarding reservation with an unknown id
    Then the reservation API responds with status 404
