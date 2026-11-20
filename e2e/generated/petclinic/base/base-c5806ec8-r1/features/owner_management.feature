Feature: Owner management
  Owners can be listed, registered, read back and updated.

  Scenario: Listing owners succeeds
    When the client lists all owners
    Then the owner response has status 200

  Scenario: A registered owner can be read back
    Given a new owner has been registered with a unique city
    When the client fetches the registered owner
    Then the owner response has status 200
    And the fetched owner shows the expected city

  Scenario: Updating the city of an owner is persisted
    Given a new owner has been registered with a unique city
    When the client changes the city of the registered owner
    Then the owner update is successful
    When the client fetches the registered owner
    Then the owner response has status 200
    And the fetched owner shows the expected city

  Scenario: Fetching an owner with an unknown id is rejected
    When the client fetches an owner with an unknown id
    Then the owner response is a client error
