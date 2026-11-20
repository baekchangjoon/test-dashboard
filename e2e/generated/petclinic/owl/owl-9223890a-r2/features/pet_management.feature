Feature: Pet management
  Pets can be created for owners, read, renamed, and pet types can be listed.

  Scenario: Pet types can be listed
    When the pet types are requested
    Then the pet API response status is 200
    And the pet types list is not empty

  Scenario: A pet created for an owner can be read back
    Given an owner and a pet type are prepared for the pet test
    When a pet with a unique name is created for the prepared owner
    Then the pet creation succeeds
    When the created pet is fetched
    Then the pet API response status is 200
    And the fetched pet has the submitted name

  Scenario: Renaming a pet is persisted
    Given an owner and a pet type are prepared for the pet test
    And a pet with a unique name is created for the prepared owner
    And the pet creation succeeds
    When the created pet is renamed
    Then the pet update succeeds
    When the created pet is fetched
    Then the pet API response status is 200
    And the fetched pet has the submitted name

  Scenario: Creating a pet with a blank name is rejected
    Given an owner and a pet type are prepared for the pet test
    When a pet with a blank name is created for the prepared owner
    Then the pet API response status is 400

  Scenario: Fetching an unknown pet is rejected
    When an unknown pet id is fetched
    Then the pet API response is a client error
