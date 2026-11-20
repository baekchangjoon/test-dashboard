Feature: Owner management API
  Owners can be listed, created, read and updated.

  Scenario: Listing owners succeeds
    When all owners are requested from the owner API
    Then the owner API request succeeds

  Scenario: Creating an owner returns an identifier
    Given a unique owner payload is prepared
    When the owner payload is posted to the owner API
    Then the owner API request succeeds
    And the owner API response carries an identifier

  Scenario: A created owner can be read back
    Given an owner has been created through the owner API
    When the created owner is fetched from the owner API
    Then the owner API request succeeds
    And the fetched owner matches the submitted names, address, city and telephone

  Scenario: Updating the city of an owner is persisted
    Given an owner has been created through the owner API
    When the created owner city is changed to a new unique value
    Then the owner API request succeeds
    And the owner fetched again has the new city

  Scenario: A created owner appears in the owner list
    Given an owner has been created through the owner API
    When all owners are requested from the owner API
    Then the owner API request succeeds
    And the owner list contains the created owner

  Scenario: Fetching an unknown owner is rejected
    When an owner with an unknown id is fetched from the owner API
    Then the owner API request is rejected with a client error

  Scenario Outline: Creating an owner with a blank <field> is rejected
    Given a unique owner payload is prepared
    And the owner payload field "<field>" is blank
    When the owner payload is posted to the owner API
    Then the owner API request is rejected with a client error

    Examples:
      | field     |
      | firstName |
      | lastName  |
      | telephone |
