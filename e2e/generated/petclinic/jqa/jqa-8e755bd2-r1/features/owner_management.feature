Feature: Owner management API
  Owners can be registered, listed, read and updated.

  Scenario: Register an owner and read it back by id
    Given a new owner has been registered via the owner API
    When the registered owner is fetched by id
    Then the owner response status is 200
    And the fetched owner has the submitted first name, last name and city

  Scenario: List all owners
    Given a new owner has been registered via the owner API
    When all owners are listed via the owner API
    Then the owner response status is 200
    And the owner list response body is a JSON document

  Scenario: Update the city of a registered owner
    Given a new owner has been registered via the owner API
    When the city of the registered owner is changed to a new value
    Then the owner update succeeds
    And fetching the registered owner shows the new city

  Scenario: Fetching an unknown owner id returns not found
    When an unknown owner id is fetched via the owner API
    Then the owner response status is 404

  Scenario Outline: Registering an owner with invalid data is rejected
    When an owner is registered with the invalid variant "<variant>"
    Then the owner response status is 400

    Examples:
      | variant               |
      | missing first name    |
      | non numeric telephone |
