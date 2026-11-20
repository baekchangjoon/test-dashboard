Feature: Pet management
  Pets can be registered for owners, read back, renamed, and pet types can be listed.

  Scenario: Pet types can be listed
    When the client lists the available pet types
    Then the pet response has status 200
    And the pet type list is a JSON array whose entries carry a name

  Scenario: Register a pet for a new owner and read it back
    Given a new owner who will own a pet
    And a new pet with a unique name registered for that owner
    When the client fetches that pet by id
    Then the pet response has status 200
    And the fetched pet has the registered name

  Scenario: Rename an existing pet
    Given a new owner who will own a pet
    And a new pet with a unique name registered for that owner
    When the client renames that pet to a new unique name
    Then the pet update succeeds
    And fetching that pet shows the new name

  Scenario: Reject a pet registration without a name
    Given a new owner who will own a pet
    When the client registers a pet without a name for that owner
    Then the pet response has status 400

  Scenario: Fetching an unknown pet returns not found
    When the client fetches a pet with an id that does not exist
    Then the pet response has status 404
