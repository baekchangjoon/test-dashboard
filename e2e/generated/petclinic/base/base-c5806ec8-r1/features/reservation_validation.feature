Feature: Boarding reservation validation and conflicts
  Invalid or conflicting reservation requests are rejected with the documented status codes.

  Scenario Outline: Invalid reservation input is rejected with bad request
    When the client submits an invalid boarding reservation of kind <kind>
    Then the boarding reservation is rejected with status 400

    Examples:
      | kind           |
      | empty-body     |
      | blank-pet-name |
      | zero-nights    |

  Scenario: Booking the same room on the same check-in date twice is a conflict
    Given a boarding reservation exists for a random room and check-in date
    When another boarding reservation is submitted for the same room and check-in date
    Then the boarding reservation is rejected with status 409

  Scenario: Updating a reservation with zero nights is rejected
    Given a boarding reservation exists for a random room and check-in date
    When the existing boarding reservation is updated with zero nights
    Then the boarding reservation is rejected with status 400
