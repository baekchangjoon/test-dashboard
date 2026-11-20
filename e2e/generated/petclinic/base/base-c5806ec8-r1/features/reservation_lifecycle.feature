Feature: Boarding reservation lifecycle
  Create, read, update and delete boarding reservations through the reservation API.

  Scenario: A created reservation can be read back with the sent pet name
    Given a new boarding reservation has been created for the lifecycle test
    When the client fetches the lifecycle reservation by its id
    Then the lifecycle reservation response has status 200
    And the fetched lifecycle reservation shows the expected pet name

  Scenario: A reservation using the WELCOME10 promo code is accepted
    When the client books a lifecycle reservation with promo code WELCOME10
    Then the lifecycle booking is accepted with an id

  Scenario: Updating the pet name of a reservation is persisted
    Given a new boarding reservation has been created for the lifecycle test
    When the client renames the pet on the lifecycle reservation
    Then the lifecycle reservation response is successful
    When the client fetches the lifecycle reservation by its id
    Then the lifecycle reservation response has status 200
    And the fetched lifecycle reservation shows the expected pet name

  Scenario: A deleted reservation can no longer be found
    Given a new boarding reservation has been created for the lifecycle test
    When the client deletes the lifecycle reservation
    Then the lifecycle reservation response is successful
    When the client fetches the lifecycle reservation by its id
    Then the lifecycle reservation response has status 404

  Scenario: Fetching a reservation with an unknown id returns not found
    When the client fetches a lifecycle reservation with an unknown id
    Then the lifecycle reservation response has status 404

  Scenario: Updating a reservation with an unknown id is rejected
    When the client updates a lifecycle reservation with an unknown id
    Then the lifecycle reservation response is a client error

  Scenario: Deleting a reservation with an unknown id is rejected
    When the client deletes a lifecycle reservation with an unknown id
    Then the lifecycle reservation response is a client error
