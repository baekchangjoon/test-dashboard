Feature: Owner management

  Scenario: List owners
    When the owner client requests the owner list
    Then the owner response status is 200

  Scenario: Register an owner and read it back
    Given a new owner has been registered through the owner API
    When the owner client fetches the registered owner
    Then the owner response status is 200
    And the fetched owner has the submitted address, city and telephone

  Scenario: Change the city of an owner and read it back
    Given a new owner has been registered through the owner API
    When the owner client changes the city of the registered owner
    Then the owner response status is successful
    When the owner client fetches the registered owner
    Then the owner response status is 200
    And the fetched owner shows the changed city
