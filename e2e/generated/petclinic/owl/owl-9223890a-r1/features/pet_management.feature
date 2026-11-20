Feature: Pet management

  Scenario: List the available pet types
    When the pet client lists the pet types
    Then the pet response status is 200
    And the pet type list is a JSON array

  Scenario: Register a pet for a new owner and read it back
    Given a pet owner and a pet type are available for the pet client
    When the pet client registers a pet with a unique name
    Then the pet response is successful
    And reading the registered pet shows its unique name

  Scenario: Rename a registered pet
    Given a pet owner and a pet type are available for the pet client
    And the pet client registers a pet with a unique name
    When the pet client renames the registered pet
    Then the pet response is successful
    And reading the registered pet shows its new name

  Scenario: Reject a pet without a name
    Given a pet owner and a pet type are available for the pet client
    When the pet client registers a pet without a name
    Then the pet response is a client error

  Scenario: Reading an unknown pet is rejected
    When the pet client reads pet id 987654321
    Then the pet response is a client error
