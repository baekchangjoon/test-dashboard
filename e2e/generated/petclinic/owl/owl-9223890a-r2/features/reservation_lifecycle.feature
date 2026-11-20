Feature: Boarding reservation lifecycle
  Create, read, update and delete boarding reservations through the reservations API.

  Scenario: A created reservation can be read back by its id
    Given a new boarding reservation has been created for the lifecycle test
    When the lifecycle reservation is fetched by its id
    Then the lifecycle response status is 200
    And the lifecycle response echoes the submitted reservation details

  Scenario: A reservation with the WELCOME10 promo code is accepted
    When a boarding reservation is created for the lifecycle test with promo code "WELCOME10"
    Then the lifecycle reservation creation succeeds with an id

  Scenario: Updating the nights of a reservation is persisted
    Given a new boarding reservation has been created for the lifecycle test
    When the lifecycle reservation is updated to 4 nights
    Then the lifecycle request succeeds
    And fetching the lifecycle reservation shows 4 nights

  Scenario: A deleted reservation can no longer be fetched
    Given a new boarding reservation has been created for the lifecycle test
    When the lifecycle reservation is deleted
    Then the lifecycle request succeeds
    And fetching the deleted lifecycle reservation returns status 404

  Scenario: Fetching an unknown reservation returns not found
    When an unknown reservation id is fetched in the lifecycle test
    Then the lifecycle response status is 404

  Scenario: Updating an unknown reservation is rejected
    When an unknown reservation id is updated in the lifecycle test
    Then the lifecycle response is a client error

  Scenario: Deleting an unknown reservation is rejected
    When an unknown reservation id is deleted in the lifecycle test
    Then the lifecycle response is a client error
