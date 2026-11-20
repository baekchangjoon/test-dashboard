Feature: Pet management API
  Pets belong to owners and have a pet type.

  Scenario: List the available pet types
    When the pet types are requested
    Then the pet response status is 200
    And the pet types response is a non-empty list

  Scenario: Create a pet for a new owner and read it back
    Given an owner and a pet type are available for the pet test
    When a pet with a unique name is created for the pet test owner
    Then the pet creation succeeds
    And the created pet can be fetched with its submitted name

  Scenario: Rename an existing pet
    Given an owner and a pet type are available for the pet test
    And a pet with a unique name is created for the pet test owner
    When the created pet is renamed
    Then the pet update succeeds
    And fetching the created pet shows the new name

  Scenario: Fetching an unknown pet id returns not found
    When an unknown pet id is fetched
    Then the pet response status is 404

  Scenario: Creating a pet without a name is rejected
    Given an owner and a pet type are available for the pet test
    When a pet without a name is created for the pet test owner
    Then the pet response status is 400
