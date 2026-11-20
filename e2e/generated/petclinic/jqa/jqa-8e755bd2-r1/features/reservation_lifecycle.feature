Feature: Boarding reservation lifecycle
  Reservations can be created, read, updated and deleted through the reservation API.

  Scenario: Create a reservation and read it back by id
    Given a new boarding reservation has been created for the lifecycle test
    When the lifecycle reservation is fetched by its id
    Then the lifecycle response status is 200
    And the fetched lifecycle reservation matches the submitted pet name and nights

  Scenario: Create a reservation using the WELCOME10 promo code
    When a boarding reservation is created with promo code "WELCOME10"
    Then the lifecycle reservation creation succeeds with an id

  Scenario: Update the number of nights of a reservation
    Given a new boarding reservation has been created for the lifecycle test
    When the lifecycle reservation is updated to 3 nights
    Then the lifecycle reservation update succeeds
    And fetching the lifecycle reservation shows 3 nights

  Scenario: Delete a reservation and verify it can no longer be read
    Given a new boarding reservation has been created for the lifecycle test
    When the lifecycle reservation is deleted
    Then the lifecycle reservation deletion succeeds
    And fetching the lifecycle reservation returns status 404

  Scenario Outline: Requests for an unknown reservation id are reported as not found
    When a lifecycle "<method>" request is sent for an unknown reservation id
    Then the lifecycle response status is 404

    Examples:
      | method |
      | GET    |
      | PUT    |
      | DELETE |
