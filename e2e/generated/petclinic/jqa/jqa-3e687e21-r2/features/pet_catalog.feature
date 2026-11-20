Feature: Pet API catalog
  Pet types can be listed and unknown pets are not found.

  Scenario: Pet types can be listed
    When the pet types are requested from the pet API
    Then the pet API request succeeds
    And the pet types response is a list

  Scenario: Every listed pet type has a name
    When the pet types are requested from the pet API
    Then the pet API request succeeds
    And every listed pet type has a non-empty name

  Scenario: Fetching an unknown pet is rejected
    When a pet with an unknown id is requested from the pet API
    Then the pet API request is rejected with a client error
