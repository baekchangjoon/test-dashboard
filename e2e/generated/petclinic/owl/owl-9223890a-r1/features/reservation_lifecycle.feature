Feature: Boarding reservation lifecycle

  Scenario: Create a boarding reservation and read it back
    Given a new boarding reservation is booked for a uniquely named pet
    When the lifecycle client reads the booked reservation
    Then the lifecycle response status is 200
    And the read reservation shows the booked pet name, room and nights

  Scenario: Create a boarding reservation with the WELCOME10 promo code
    When the lifecycle client books a reservation with promo code "WELCOME10"
    Then the lifecycle booking succeeds with a generated id
    And the booked reservation can be read back with status 200

  Scenario: Update the number of nights of an existing reservation
    Given a new boarding reservation is booked for a uniquely named pet
    When the lifecycle client changes the booked reservation to 4 nights
    Then the lifecycle update succeeds
    And reading the booked reservation shows 4 nights

  Scenario: Delete an existing reservation
    Given a new boarding reservation is booked for a uniquely named pet
    When the lifecycle client deletes the booked reservation
    Then the lifecycle delete succeeds
    And reading the booked reservation returns status 404

  Scenario: Deleting the same reservation twice fails the second time
    Given a new boarding reservation is booked for a uniquely named pet
    And the lifecycle client deletes the booked reservation
    When the lifecycle client deletes the booked reservation
    Then the lifecycle response is a client error

  Scenario: Reading an unknown reservation returns not found
    When the lifecycle client reads reservation id 987654321
    Then the lifecycle response status is 404

  Scenario: Updating an unknown reservation is rejected
    When the lifecycle client updates reservation id 987654321 with valid data
    Then the lifecycle response is a client error

  Scenario: Deleting an unknown reservation is rejected
    When the lifecycle client deletes reservation id 987654321
    Then the lifecycle response is a client error
