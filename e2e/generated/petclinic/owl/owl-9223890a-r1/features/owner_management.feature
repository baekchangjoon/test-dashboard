Feature: Owner management

  Scenario: Register an owner and read the owner back
    Given a new owner with a unique last name is registered
    When the owner client reads the registered owner
    Then the owner response status is 200
    And the owner response shows the registered names, address, city and telephone

  Scenario: The owner list includes a newly registered owner
    Given a new owner with a unique last name is registered
    When the owner client lists all owners
    Then the owner response status is 200
    And the owner response mentions the registered last name

  Scenario: Update the city of a registered owner
    Given a new owner with a unique last name is registered
    When the owner client changes the city of the registered owner to a new unique city
    Then the owner response is successful
    And reading the registered owner shows the new city

  Scenario: Reading an unknown owner is rejected
    When the owner client reads owner id 987654321
    Then the owner response is a client error

  Scenario Outline: Reject owner registration with invalid data of kind <kind>
    When the owner client registers an owner with invalid data of kind "<kind>"
    Then the owner response is a client error

    Examples:
      | kind                  |
      | blank-first-name      |
      | blank-last-name       |
      | blank-city            |
      | non-numeric-telephone |
