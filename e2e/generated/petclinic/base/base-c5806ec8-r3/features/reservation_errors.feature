Feature: Boarding reservation error handling

  Scenario: Creating a reservation with an empty body is rejected
    When a boarding reservation is submitted with an empty body
    Then the reservation error response has status 400

  Scenario Outline: Creating a reservation with a negative numeric field is rejected
    When a boarding reservation is submitted with "<field>" set to -1
    Then the reservation error response has status 400

    Examples:
      | field       |
      | nights      |
      | animalCount |

  Scenario: Booking the same room for the same dates twice is a conflict
    Given a boarding reservation request body has been accepted once
    When the identical boarding reservation request is submitted again
    Then the reservation error response has status 409

  Scenario: Fetching an unknown reservation returns not found
    When an unknown boarding reservation id is fetched
    Then the reservation error response has status 404

  Scenario: Updating an unknown reservation is rejected
    When an unknown boarding reservation id is updated
    Then the reservation error response is a client error

  Scenario: Deleting an unknown reservation is rejected
    When an unknown boarding reservation id is deleted
    Then the reservation error response is a client error

  Scenario: Deleting a reservation twice is rejected the second time
    Given an existing boarding reservation for error checks
    When that boarding reservation is deleted twice
    Then the reservation error response is a client error
