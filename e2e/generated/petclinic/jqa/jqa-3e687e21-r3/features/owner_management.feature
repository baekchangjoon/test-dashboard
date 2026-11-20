Feature: Owner management
  Pet owners can be registered, listed, read and updated.

  Scenario: Register a new owner and read it back
    Given a newly registered owner with a unique name
    When the client fetches that owner by id
    Then the owner response has status 200
    And the fetched owner matches the registered first name, last name and city

  Scenario: Owner list includes a newly registered owner
    Given a newly registered owner with a unique name
    When the client lists all owners
    Then the owner response has status 200
    And the owner list contains the newly registered owner

  Scenario: Update the city of an existing owner
    Given a newly registered owner with a unique name
    When the client changes that owner's city to a new unique city
    Then the owner update succeeds
    And fetching that owner shows the new city

  Scenario Outline: Reject an owner registration with invalid data
    When the client registers an owner whose "<field>" is "<value>"
    Then the owner response has status 400

    Examples:
      | field     | value       |
      | firstName |             |
      | telephone | not-a-phone |

  Scenario: Fetching an unknown owner returns not found
    When the client fetches an owner with an id that does not exist
    Then the owner response has status 404
