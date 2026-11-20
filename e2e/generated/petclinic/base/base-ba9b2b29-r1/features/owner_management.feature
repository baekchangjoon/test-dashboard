Feature: Managing owners

  Scenario: Listing owners succeeds
    When all owners are requested
    Then the owners request responds with status 200

  Scenario: Registering a new owner returns an id
    Given a new owner with unique contact details
    When the new owner is registered
    Then the owner registration succeeds with an id

  Scenario: A registered owner can be read back by id
    Given a new owner with unique contact details
    When the new owner is registered
    Then the owner registration succeeds with an id
    When the registered owner is fetched by id
    Then the fetched owner shows the registered address, city and telephone

  Scenario: Updating an owner changes the city
    Given a new owner with unique contact details
    When the new owner is registered
    Then the owner registration succeeds with an id
    When the registered owner city is changed to a unique value
    Then the owner update succeeds
    When the registered owner is fetched by id
    Then the fetched owner shows the changed city
