Feature: Veterinarian directory
  Veterinarians can be listed and looked up individually.

  Scenario: Veterinarians can be listed
    When the client lists all veterinarians
    Then the veterinarian response has status 200
    And the veterinarian list is a JSON document

  Scenario: A listed veterinarian can be fetched individually
    When the client lists all veterinarians
    And the client fetches the first listed veterinarian if any exists
    Then the veterinarian lookup succeeds for the fetched veterinarian

  Scenario: Fetching an unknown veterinarian returns not found
    When the client fetches a veterinarian with an id that does not exist
    Then the veterinarian response has status 404
