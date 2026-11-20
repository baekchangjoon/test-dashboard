Feature: Boarding reservation input validation
  Invalid reservation input is rejected with a bad request status.

  Scenario Outline: Creating a reservation with invalid input is rejected
    When a reservation is submitted with the invalid variant "<variant>"
    Then the reservation validation response status is 400

    Examples:
      | variant         |
      | empty object    |
      | no body         |
      | negative nights |
      | blank pet name  |

  Scenario: Updating a reservation with a negative number of nights is rejected
    Given a valid reservation exists for the validation test
    When the validation reservation is updated with -1 nights
    Then the reservation validation response status is 400
