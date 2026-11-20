Feature: Owner management
  Owners can be registered, read, updated and listed through the owners API.

  Scenario: A registered owner can be read back by id
    Given a new owner has been registered through the owner API
    When the registered owner is fetched by id
    Then the owner API response status is 200
    And the fetched owner shows the submitted names and city

  Scenario: Changing the city of an owner is persisted
    Given a new owner has been registered through the owner API
    When the city of the registered owner is changed to a new value
    Then the owner update succeeds
    And fetching the registered owner shows the new city

  Scenario: Listing owners succeeds
    Given a new owner has been registered through the owner API
    When all owners are listed
    Then the owner API response status is 200
    And the owner listing body is not empty

  Scenario Outline: Registering an owner with an invalid field is rejected
    When an owner is registered with field "<field>" set to "<value>"
    Then the owner API response status is 400

    Examples:
      | field     | value  |
      | firstName |        |
      | city      |        |
      | telephone | abcdef |

  Scenario: Fetching an unknown owner is rejected
    When an unknown owner id is fetched through the owner API
    Then the owner API response is a client error
