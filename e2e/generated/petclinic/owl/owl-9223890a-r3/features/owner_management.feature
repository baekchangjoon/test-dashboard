Feature: Owner management API
  Owners can be registered, read, listed and updated.

  Scenario: Register an owner and read it back
    Given a new owner payload with unique names
    When the owner payload is submitted
    Then the owner is created with an id
    And reading the owner by id returns the submitted names, city and telephone

  Scenario: List owners after registering one
    Given an existing owner created through the owner API
    When all owners are listed
    Then the owner listing response is successful and not empty

  Scenario: Change the city of an existing owner
    Given an existing owner created through the owner API
    When the city of the owner is changed to a unique value
    Then the owner update succeeds
    And reading the owner by id shows the new city

  Scenario Outline: Registering an owner with an invalid <field> is rejected
    Given a new owner payload with unique names
    When the owner payload field "<field>" is set to "<value>" and submitted
    Then the owner request is rejected with a client error

    Examples:
      | field     | value |
      | firstName |       |
      | city      |       |
      | telephone | abc   |

  Scenario: Reading an unknown owner is a client error
    When the owner with id 987654321 is requested
    Then the owner request is rejected with a client error

  Scenario: Updating an owner with a blank last name is rejected
    Given an existing owner created through the owner API
    When the existing owner is updated with a blank last name
    Then the owner request is rejected with a client error
