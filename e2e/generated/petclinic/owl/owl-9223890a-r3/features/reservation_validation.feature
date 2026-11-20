Feature: Boarding reservation validation and error handling
  Invalid input, unknown ids and conflicting bookings are rejected with documented status codes.

  Scenario: Creating a reservation from an empty request body is rejected
    When an empty reservation creation request is submitted
    Then the reservation validation response status is 400

  Scenario Outline: Creating a reservation with an invalid <field> is rejected
    Given a valid reservation request for validation checks
    When the reservation request field "<field>" is set to "<value>" and submitted
    Then the reservation validation response status is 400

    Examples:
      | field       | value |
      | petName     |       |
      | nights      | 0     |
      | nights      | -1    |
      | animalCount | 0     |

  Scenario: Booking the same room for the same check-in date twice is a conflict
    Given a boarding reservation already exists for a room and check-in date
    When another reservation is submitted for the same room and check-in date
    Then the reservation validation response status is 409

  Scenario: Reading an unknown reservation returns not found
    When a reservation with id 987654321 is requested
    Then the reservation validation response status is 404

  Scenario: Updating an unknown reservation returns not found
    When the reservation with id 987654321 is updated with valid data
    Then the reservation validation response status is 404

  Scenario: Deleting an unknown reservation returns not found
    When the reservation with id 987654321 is deleted
    Then the reservation validation response status is 404

  Scenario: Updating a reservation to zero nights is rejected
    Given an existing reservation for validation checks
    When the existing reservation is updated with 0 nights
    Then the reservation validation response status is 400
