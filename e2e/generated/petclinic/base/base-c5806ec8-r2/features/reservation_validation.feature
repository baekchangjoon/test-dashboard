Feature: Boarding reservation validation and conflicts

  Scenario: Reject an empty reservation request
    When the validation client submits an empty reservation request
    Then the validation response status is 400

  Scenario Outline: Reject a reservation request with an invalid field value
    Given a valid reservation request prepared for the validation check
    And the prepared validation request has "<field>" set to "<value>"
    When the validation client submits the prepared reservation request
    Then the validation response status is 400

    Examples:
      | field      | value        |
      | nights     | 0            |
      | nights     | -1           |
      | petName    |              |
      | ownerEmail | not-an-email |

  Scenario: Reject a second reservation for the same room and check-in date
    Given an existing reservation created for the conflict check
    When the validation client submits another reservation for the same room and check-in date
    Then the validation response status is 409

  Scenario: Reject moving a reservation onto an occupied room and date
    Given an existing reservation created for the conflict check
    And a second reservation in a different slot created for the conflict check
    When the validation client moves the second reservation onto the room and date of the first
    Then the validation response status is 409

  Scenario: Reject updating a reservation with zero nights
    Given an existing reservation created for the conflict check
    When the validation client updates the existing reservation with 0 nights
    Then the validation response status is 400
