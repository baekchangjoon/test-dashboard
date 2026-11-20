Feature: Boarding reservation validation and conflicts

  Scenario: Submitting a reservation without a body is rejected
    When the client submits a boarding reservation without a request body
    Then the reservation validation responds with status 400

  Scenario: Submitting an empty reservation object is rejected
    When the client submits an empty boarding reservation object
    Then the reservation validation responds with status 400

  Scenario Outline: Submitting a reservation with an invalid field value is rejected
    When the client submits a boarding reservation where "<field>" is set to "<value>"
    Then the reservation validation responds with status 400

    Examples:
      | field       | value        |
      | nights      | 0            |
      | nights      | -1           |
      | animalCount | 0            |
      | ownerEmail  | not-an-email |
      | petName     |              |

  Scenario: Booking an already occupied room on the same date is a conflict
    Given a boarding reservation already occupies a room on a check-in date
    When the client books the same room for the same check-in date
    Then the reservation validation responds with status 409

  Scenario: Updating a reservation to zero nights is rejected
    Given a boarding reservation already occupies a room on a check-in date
    When the client updates that occupied reservation setting nights to 0
    Then the reservation validation responds with status 400
