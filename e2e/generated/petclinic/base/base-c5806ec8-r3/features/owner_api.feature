Feature: Owner management API

  Scenario: List owners
    When the owner list is requested
    Then the owner list response has status 200

  Scenario: Create an owner and read it back
    Given a new owner has been registered through the API
    When the registered owner is fetched by id
    Then the fetched owner has the submitted city and telephone

  Scenario: Update the city of an owner
    Given a new owner has been registered through the API
    When the registered owner is updated with a new city
    Then the owner update succeeds
    And fetching the registered owner shows the new city
