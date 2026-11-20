Feature: Boarding reservation validation and conflicts
  Invalid or conflicting reservation requests are rejected with the documented status codes.

  Scenario Outline: Creating a reservation with invalid input is rejected
    When a reservation is submitted with the invalid variation "<variation>"
    Then the reservation validation response status is 400

    Examples:
      | variation       |
      | empty body      |
      | zero nights     |
      | negative nights |
      | blank pet name  |

  Scenario: Booking the same reservation twice is rejected as a conflict
    Given a reservation has been booked for the conflict test
    When the identical reservation is booked again
    Then the reservation validation response status is 409

  Scenario: Updating a reservation to zero nights is rejected
    Given a reservation has been booked for the conflict test
    When the booked reservation is updated to 0 nights in the validation test
    Then the reservation validation response status is 400
