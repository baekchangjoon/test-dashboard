Feature: Boarding reservation input validation
  Invalid reservation requests are rejected with a bad request status.

  Scenario: Submitting an empty reservation body is rejected
    When an empty boarding reservation body is submitted
    Then the reservation validation response status is 400

  Scenario Outline: A reservation without <field> is rejected
    Given a valid reservation validation payload
    And the reservation validation payload has no "<field>"
    When the reservation validation payload is submitted
    Then the reservation validation response status is 400

    Examples:
      | field      |
      | petName    |
      | ownerEmail |

  Scenario Outline: A reservation with a negative <field> is rejected
    Given a valid reservation validation payload
    And the reservation validation payload sets "<field>" to -1
    When the reservation validation payload is submitted
    Then the reservation validation response status is 400

    Examples:
      | field       |
      | nights      |
      | animalCount |
