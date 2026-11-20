Feature: Pet management API
  Pet types can be listed and pets can be created, read and updated for an owner.

  Scenario: List the available pet types
    When the pet types are listed
    Then the pet type listing is successful and not empty

  Scenario: Create a pet for a new owner and read it back
    Given an owner and a pet type are available for a new pet
    When a pet with a unique name is created for that owner
    Then the pet is created with an id
    And reading the pet by id returns the latest pet name

  Scenario: Rename an existing pet
    Given an existing pet created through the pet API
    When the pet is renamed to a unique name
    Then the pet update succeeds
    And reading the pet by id returns the latest pet name

  Scenario: Creating a pet with a blank name is rejected
    Given an owner and a pet type are available for a new pet
    When a pet with a blank name is created for that owner
    Then the pet request is rejected with a client error

  Scenario: Reading an unknown pet is a client error
    When the pet with id 987654321 is requested
    Then the pet request is rejected with a client error
