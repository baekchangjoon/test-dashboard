Feature: Owner management API

  Scenario: Listing owners succeeds for an authenticated client
    When the client requests the owner list
    Then the owner API responds with status 200

  Scenario: A created owner can be read back with the submitted names
    Given a new owner has been registered with unique data
    When the client fetches the registered owner
    Then the owner API responds with status 200
    And the fetched owner has the registered first name and last name

  Scenario: Updating an owner changes the stored city
    Given a new owner has been registered with unique data
    When the client updates the registered owner city to a new unique value
    Then the owner update is accepted
    And fetching the registered owner shows the new city

  Scenario Outline: Creating an owner with a blank required field is rejected
    When the client registers an owner with blank "<field>"
    Then the owner API responds with status 400

    Examples:
      | field     |
      | firstName |
      | lastName  |
      | address   |
      | city      |
      | telephone |

  Scenario: Creating an owner with a non numeric telephone is rejected
    When the client registers an owner with telephone "abc-phone"
    Then the owner API responds with status 400

  Scenario: Fetching an unknown owner fails
    When the client fetches an owner with an unknown id
    Then the owner lookup fails with a client error
