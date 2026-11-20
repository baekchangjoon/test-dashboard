Feature: Boarding reservation validation and conflicts

  Scenario Outline: Reject an invalid reservation request of kind <kind>
    When the validation client submits an invalid reservation of kind "<kind>"
    Then the validation response status is 400

    Examples:
      | kind            |
      | empty-body      |
      | blank-pet-name  |
      | zero-nights     |
      | negative-nights |
      | zero-animals    |

  Scenario: Reject a second reservation for the same room and check-in date
    Given the validation client has booked a room on a future date
    When the validation client books the same room on the same date for another pet
    Then the validation response status is 409

  Scenario: Reject an update that sets nights to zero
    Given the validation client has booked a room on a future date
    When the validation client updates that reservation to 0 nights
    Then the validation response status is 400

  Scenario: Reject an update that moves a reservation onto an occupied room and date
    Given the validation client has booked a room on a future date
    And the validation client has booked the same room 20 days later
    When the validation client moves the later reservation onto the first check-in date
    Then the validation response status is 409
